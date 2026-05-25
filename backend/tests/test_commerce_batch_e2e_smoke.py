"""W15-E2E: 批量生成 + 变体克隆 + 冠军标记 端到端 smoke 测试。

本测试是 P2 阶段的"完成验收闸门"：把 W14-T1（批量入队 worker）→
W14-T3（克隆 / 冠军服务）→ W6-T2（变体列表）四条线串起来用一个
async 测试一次性走完，确保 P2 后端的"参数网格扫描 → 列表查看 →
A/B 派生 → 冠军评估"完整链路在同一份数据库 + 同一个 FastAPI 应用
上能跑通。

为什么只写一个测试函数：
    与 W9-T2 ``test_commerce_e2e_smoke.py`` 的"smoke 闸门"定位对齐。
    覆盖率由 :mod:`test_story_video_batch_generate_worker`、
    :mod:`test_story_variants_api` 等单测提供；本测试只负责证明"全
    链路可走通"，CI 一旦红能直接定位"流程级回归"而不是"局部 bug"。

测试编排：
    1. 端到端涉及到的 ORM 必须在 ``Base.metadata.create_all`` 之前
       *全部 import 进来*（与 ``test_commerce_e2e_smoke.py`` 一致），
       否则 ``Base.metadata`` 会缺表。
    2. 启动期 seed（prompts / formulas / compliance）通过
       :func:`bootstrap_async_state` 一次性写入测试库；这正是 FastAPI
       lifespan 在生产上做的事，复用它能让闸门验证"启动种子链路"是
       否完整。
    3. 把 FastAPI 应用 ``get_db`` 依赖覆盖到测试 sessionmaker，让所有
       HTTP 调用都打到同一个 SQLite 文件；同时 monkeypatch worker 内
       部的 ``async_session_maker`` 与 ``story_script_generate_worker``
       的同名引用，让 worker 直接调用时也使用同一个库。
    4. LLM 全部走 mock：``langchain_openai.ChatOpenAI`` 被替换为返回
       canned 响应的 ``BaseChatModel``，``a_generate_script`` 被
       monkeypatch 直接返回 canned :class:`StoryScript`，保证既不触
       网也不打钱；Celery ``send_task`` 被 :class:`MagicMock` 拦截。

预期结果：
    - 8 个 sub-step 全部通过；
    - 6 个子任务行 + 3 个就绪变体 + 1 个克隆草稿 + 1 个冠军；
    - ``(project_id, chapter_id)`` 命名空间内冠军唯一性成立。
"""

# pylint: disable=invalid-name,redefined-outer-name,too-many-locals,too-many-statements

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# 必须 import 全部模型，确保 Base.metadata 拥有完整 schema。
import app.models.api_quota  # noqa: F401  pylint: disable=unused-import
import app.models.commerce_assets  # noqa: F401  pylint: disable=unused-import
import app.models.compliance  # noqa: F401  pylint: disable=unused-import
import app.models.llm  # noqa: F401  pylint: disable=unused-import
import app.models.story_formula  # noqa: F401  pylint: disable=unused-import
import app.models.studio  # noqa: F401  pylint: disable=unused-import
import app.models.studio_prompts_files_timeline  # noqa: F401  pylint: disable=unused-import
import app.models.task  # noqa: F401  pylint: disable=unused-import
import app.models.task_links  # noqa: F401  pylint: disable=unused-import

from app.bootstrap import bootstrap_async_state
from app.core.db import Base
from app.dependencies import get_db
from app.main import app
from app.models.llm import (
    Model,
    ModelCategoryKey,
    ModelSettings,
    Provider,
)
from app.models.story_formula import StoryVariant
from app.models.studio import Chapter
from app.models.task import GenerationTask, GenerationTaskStatus
from app.models.types import (
    ChapterStatus,
    ProductCategory,
    ProjectKind,
    ProjectStyle,
    ProjectVisualStyle,
)
from app.services.commerce.story_script_generate_worker import (
    run_story_script_generate_task,
)
from app.services.commerce.story_video_batch_generate_worker import (
    CHILD_TASK_KIND,
    run_story_video_batch_generate_task,
)


# ---------------------------------------------------------------------------
# 1) Mock LLM + 共享数据库 fixture
# ---------------------------------------------------------------------------


class _MockChatModel(BaseChatModel):
    """LangChain ``BaseChatModel`` 占位实现：恒定返回固定字符串。

    用于覆盖 ``langchain_openai.ChatOpenAI``，使 build_default_text_llm
    在测试环境下返回一个不会触网的 chat model。``response`` 由调用方
    用 ``object.__setattr__`` 注入，绕开 pydantic 的字段校验。
    """

    response: str = ""

    def __init__(self, response: str = "", **_kwargs: Any) -> None:
        super().__init__()
        object.__setattr__(self, "response", response)

    @property
    def _llm_type(self) -> str:  # pragma: no cover - LangChain 协议要求
        return "mock-batch-e2e-smoke-chat-model"

    def _generate(  # type: ignore[override]
        self,
        messages: Any,  # pylint: disable=unused-argument
        stop: Any = None,  # pylint: disable=unused-argument
        run_manager: Any = None,  # pylint: disable=unused-argument
        **_kwargs: Any,
    ) -> ChatResult:
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=self.response))]
        )


def _canned_story_script_dict(formula_id: str) -> dict[str, Any]:
    """供 StoryScriptGeneratorAgent 在 mock 路径中返回的 StoryScript 模型 dump。

    与 W9-T2 测试一致：4 个 shot、每个 15 秒、共 60 秒；``formula_id``
    透传以便子任务对应不同公式的调用都能得到与入参对齐的脚本。
    """
    per_shot = 60 / 4
    return {
        "total_duration_sec": 60,
        "total_shots": 4,
        "formula_id": formula_id,
        "shots": [
            {
                "id": f"shot_{i:03d}",
                "duration_sec": per_shot,
                "function": "generic",
                "shot_type": "medium",
                "camera_angle": "eye_level",
                "camera_movement": "static",
                "dialog": "今天给大家推荐一款产品。",
                "narration": None,
                "product_focus_level": "none",
                "is_punchline": False,
                "is_brand_mention": False,
                "notes": None,
            }
            for i in range(1, 5)
        ],
        "opening_hook": "你试过这个吗",
        "cta_text": "点击购物车下单",
        "brand_mention_count": 0,
    }


@pytest_asyncio.fixture
async def session_factory(tmp_path) -> AsyncGenerator[
    async_sessionmaker[AsyncSession], None
]:
    """构造一次性 SQLite 文件 DB，建表，跑 bootstrap_async_state 写种子。

    用文件型 SQLite（而不是 ``:memory:``）的原因：worker 入口会自己开
    ``async_session_maker()`` 上下文，多次 connect 必须看到同一个
    schema/数据；``:memory:`` 每个 connection 是独立内存库，会破坏断言。
    """

    db_path = tmp_path / "commerce-batch-e2e-smoke.db"
    engine: AsyncEngine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}", future=True
    )
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 跑全套 bootstrap：写入 prompt + cn 公式 + 合规规则。
    async with sm() as setup_db:
        await bootstrap_async_state(setup_db)
        # 默认文本 LLM provider/model/settings：让 build_default_text_llm
        # 能解析出可用模型；真正的 ChatOpenAI 会在测试中被 monkeypatch。
        setup_db.add(
            Provider(
                id="prov-1",
                name="MockProvider",
                base_url="http://example.invalid",
                api_key="sk-test",
            )
        )
        setup_db.add(
            Model(
                id="model-1",
                provider_id="prov-1",
                name="mock-text-model",
                category=ModelCategoryKey.text,
                params={},
            )
        )
        setup_db.add(
            ModelSettings(
                id=1,
                default_text_model_id="model-1",
                default_image_model_id=None,
                default_video_model_id=None,
            )
        )
        await setup_db.commit()

    try:
        yield sm
    finally:
        await engine.dispose()


@pytest.fixture
def client_with_db(
    session_factory: async_sessionmaker[AsyncSession],
) -> Generator[TestClient, None, None]:
    """覆盖 ``get_db``，让所有 FastAPI 路由命中测试库。"""

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


async def _seed_chapter(
    sm: async_sessionmaker[AsyncSession], project_id: str, chapter_id: str
) -> None:
    """直接 DB 写一条 Chapter（commerce_story 项目目前没有公开的
    chapter 创建路径，按测试要求手动 seed）。"""
    async with sm() as session:
        session.add(
            Chapter(
                id=chapter_id,
                project_id=project_id,
                index=1,
                title="第一章",
                summary="",
                raw_text="",
                condensed_text="",
                storyboard_count=0,
                status=ChapterStatus.draft,
            )
        )
        await session.commit()


# ---------------------------------------------------------------------------
# 2) The single "P2 batch + clone + champion" gate test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commerce_batch_full_user_journey(  # noqa: PLR0915
    session_factory: async_sessionmaker[AsyncSession],
    client_with_db: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """全链路 P2 smoke：批量入队 → 子任务执行 → 列表 → 克隆 → 冠军。

    8 个 sub-step 一次性串起来；任何一步红就证明 P2 闸门未达成。
    """

    # ------------------------------------------------------------------
    # Mock LLM 路径：worker 入口会调用 build_default_text_llm{,_sync}，
    # 它内部 import ``langchain_openai.ChatOpenAI``。把它替换成"返回
    # mock chat model"，使子任务 worker 不实际触网。
    # ------------------------------------------------------------------

    def _factory_chat_openai(**_kwargs: Any) -> BaseChatModel:
        # 子任务 worker 会通过 monkeypatch 直接替掉
        # ``a_generate_script``，因此这里返回的内容不会被真正消费；
        # 仅用于让 build_default_text_llm 不触网。
        return _MockChatModel("")

    monkeypatch.setattr("langchain_openai.ChatOpenAI", _factory_chat_openai)

    # 直接替掉 StoryScriptGeneratorAgent 的 a_generate_script，让其
    # 返回 canned StoryScript（不经过任何 LangChain JSON 解析路径，
    # 因为脚本协议较复杂，mock 单一字符串容易触发结构校验失败）。
    async def _mock_a_generate_script(
        self: Any,  # noqa: ARG001  pylint: disable=unused-argument
        *,
        vars: Any,  # noqa: ARG001  pylint: disable=redefined-builtin
    ) -> Any:
        from app.core.contracts.story import StoryScript  # 局部 import 防循环

        # 透传 formula_id 进 canned dict，让不同公式的子任务在脚本里
        # 也能区分开（断言时 variant.formula_id 与 vars 一致）。
        formula_id = getattr(vars, "formula_id", "underdog_triumph")
        return StoryScript.model_validate(_canned_story_script_dict(formula_id))

    monkeypatch.setattr(
        "app.chains.agents.commerce.story_script_generator_agent."
        "StoryScriptGeneratorAgent.a_generate_script",
        _mock_a_generate_script,
    )

    # 让批量 worker 与子任务 worker 内部 ``async_session_maker`` 都指向
    # 测试库。FastAPI 依赖已经被 ``client_with_db`` fixture 覆盖了，但
    # worker 是直接 ``await`` 调用、不走依赖注入，因此必须显式 monkeypatch。
    monkeypatch.setattr(
        "app.services.commerce.story_video_batch_generate_worker.async_session_maker",
        session_factory,
    )

    client = client_with_db

    # ==================================================================
    # Step 1: 创建项目 + 章节（前置数据）。
    # commerce_story 项目目前没有公开的 chapter 创建路径，按测试要求
    # 直接走 ``story-projects`` 创建项目，再手动 seed Chapter。
    # ==================================================================
    project_id = "sp_batch_e2e"
    chapter_id = "chap_batch_e2e"
    formula_id = "underdog_triumph"
    create_project_body: dict[str, Any] = {
        "id": project_id,
        "name": "P2 批量带货项目",
        "description": "P2 batch smoke 项目",
        "style": ProjectStyle.real_people_city.value,
        "visual_style": ProjectVisualStyle.live_action.value,
        "seed": 1,
        "unify_style": True,
        "progress": 0,
        "default_video_ratio": None,
        "stats": {},
        "config": {
            "target_platform": "douyin",
            "target_duration_sec": 60,
            "formula_id": formula_id,
            "archetype": None,
            "tone_grid": {"formality": 0.3, "energy": 0.7},
            "audience_override": None,
            "compliance_region": "cn_mainland",
            "compliance_profile_id": "cn_mainland_default",
            "target_kpi": "conversion",
        },
    }
    res = client.post("/api/v1/studio/story-projects", json=create_project_body)
    assert res.status_code == 201, res.text
    project_data = res.json()["data"]
    assert project_data["id"] == project_id
    assert project_data["kind"] == ProjectKind.commerce_story.value

    # 项目落库后再 seed Chapter（chapter.project_id 外键依赖项目存在）。
    await _seed_chapter(session_factory, project_id, chapter_id)

    # ==================================================================
    # Step 2: POST /api/v1/commerce/story-batches 入队 6 变体。
    #
    # 期望：
    #   - 接口返回 202，``data.task_id`` 为批量任务 ID；
    #   - dispatch 服务调用 ``celery_app.send_task`` 1 次（投递批量任务）。
    #
    # 注意：``story-batches`` 接口本身只落 1 个 batch GenerationTask 行
    # 并触发 1 次 send_task；真正的"6 个子任务"由批量 worker 执行时入
    # 队，需要在下一步显式 await batch worker。
    # ==================================================================
    common_product = {
        "name": "维生素 C 精华液",
        "brand": "Acme",
        "category": ProductCategory.other.value,
    }
    common_audience = {"persona": "office_worker", "pain": "dull_skin"}
    archetypes = ["sage", "hero", "rebel", "explorer", "creator", "caregiver"]
    formulas_for_variants = [
        "underdog_triumph",
        "contrast_surprise",
        "workplace_hero",
        "family_conflict",
        "mystery_twist",
        "time_travel",
    ]
    variants_spec: list[dict[str, Any]] = [
        {
            "formula_id": formulas_for_variants[i],
            "archetype": archetypes[i],
            "hook_pattern_id": f"hook_pattern_{i + 1}",
            "tone_grid": {"formality": 3, "energy": 7},
            "label": f"v{i + 1}-{archetypes[i]}",
        }
        for i in range(6)
    ]
    batch_body: dict[str, Any] = {
        "project_id": project_id,
        "chapter_id": chapter_id,
        "product": common_product,
        "audience": common_audience,
        "target_duration_sec": 60,
        "platform": "douyin",
        "variants": variants_spec,
        "parallelism": 2,
    }

    with patch(
        "app.services.commerce.task_dispatch.celery_app.send_task"
    ) as dispatch_send_task:
        res = client.post("/api/v1/commerce/story-batches", json=batch_body)
        assert res.status_code == 202, res.text
        # dispatch 服务对批量任务自身投递 1 次 send_task。
        assert dispatch_send_task.call_count == 1
        dispatch_call = dispatch_send_task.call_args
        # batch 任务必须落到 slow 队列。
        assert dispatch_call.kwargs["queue"] == "slow"

    enqueue_payload = res.json()["data"]
    batch_task_id: str = enqueue_payload["task_id"]
    assert isinstance(batch_task_id, str) and batch_task_id
    assert enqueue_payload["task_kind"] == "story_video_batch_generate"
    assert enqueue_payload["status"] == GenerationTaskStatus.pending.value

    # ==================================================================
    # Step 3: 显式 await 批量 worker，让它把 6 个子任务行落库 + 投递
    # ``send_task`` 6 次。
    #
    # 期望：
    #   - send_task 被调 6 次（每个变体 1 次，全部投到 fast 队列）；
    #   - DB 里多出 6 行 ``task_kind=story_script_generate`` 子任务；
    #   - 每行 ``payload['parent_batch_id']`` 等于 batch_task_id；
    #   - worker 返回的 ``child_task_ids`` 列表长度 = 6 且元素互不相同。
    # ==================================================================
    fake_send = MagicMock()
    batch_result = await run_story_video_batch_generate_task(
        batch_task_id,
        batch_body,
        session_factory=session_factory,
        send_task=fake_send,
    )
    assert batch_result["batch_id"] == batch_task_id
    assert batch_result["status"] == "enqueued"
    assert batch_result["variant_count"] == 6
    child_task_ids: list[str] = batch_result["child_task_ids"]
    assert len(child_task_ids) == 6
    assert len(set(child_task_ids)) == 6, "child task ids must be globally unique"
    assert fake_send.call_count == 6
    for call in fake_send.call_args_list:
        assert call.kwargs["queue"] == "fast"

    # DB 校验：6 行子任务都落库 + parent_batch_id 正确。
    async with session_factory() as session:
        child_rows = list(
            (
                await session.execute(
                    select(GenerationTask).where(
                        GenerationTask.task_kind == CHILD_TASK_KIND
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(child_rows) == 6
    persisted_ids = {row.id for row in child_rows}
    assert persisted_ids == set(child_task_ids)
    for row in child_rows:
        assert row.payload["parent_batch_id"] == batch_task_id
        assert row.task_kind == CHILD_TASK_KIND
        assert row.status == GenerationTaskStatus.pending
        run_args = row.payload["run_args"]
        assert run_args["project_id"] == project_id
        assert run_args["chapter_id"] == chapter_id
        assert run_args["target_duration_sec"] == 60
        assert run_args["platform"] == "douyin"

    # ==================================================================
    # Step 4: 手动 await 6 个子任务里的 3 个，让它们各自产出 1 个
    # ``status=ready`` 的 StoryVariant（mock LLM 透传 formula_id）。
    # ==================================================================
    selected_child_ids = child_task_ids[:3]
    expected_archetypes = archetypes[:3]
    expected_formulas = formulas_for_variants[:3]
    generated_variant_ids: list[str] = []
    for idx, child_id in enumerate(selected_child_ids):
        # 从 DB 取出子任务 run_args，模拟"Celery 消费者拉到这一行后调
        # 用对应 worker"的真实链路。
        async with session_factory() as session:
            child_row = (
                await session.execute(
                    select(GenerationTask).where(GenerationTask.id == child_id)
                )
            ).scalar_one()
            child_run_args: dict[str, Any] = dict(child_row.payload["run_args"])

        # 批量 worker 仅写入 ``formula_id``；脚本生成 worker 还要求
        # ``formula`` 完整结构。生产路径上 Celery 消费者会从 DB 反查公
        # 式后再调脚本 worker，本测试用占位 dict 模拟该步骤即可。
        child_run_args["formula"] = {
            "id": child_run_args["formula_id"],
            "beats": ["hook", "reveal", "cta"],
        }

        # 子任务 worker 默认走 ``async_session_maker``；这里通过显式
        # ``session_factory`` 注入测试库。
        script_output = await run_story_script_generate_task(
            child_id,
            child_run_args,
            session_factory=session_factory,
        )
        variant_id: str = script_output["variant_id"]
        assert isinstance(variant_id, str) and variant_id
        generated_variant_ids.append(variant_id)

        async with session_factory() as session:
            variant = (
                await session.execute(
                    select(StoryVariant).where(StoryVariant.id == variant_id)
                )
            ).scalar_one()
            assert variant.project_id == project_id
            assert variant.chapter_id == chapter_id
            assert variant.formula_id == expected_formulas[idx]
            assert variant.archetype == expected_archetypes[idx]
            assert variant.status == "ready"
            assert variant.is_champion is False

    # ==================================================================
    # Step 5: GET /api/v1/studio/story-variants?project_id=...
    # 期望：3 个 ready 变体（与 step 4 生成一一对应）。
    # ==================================================================
    res = client.get(f"/api/v1/studio/story-variants?project_id={project_id}")
    assert res.status_code == 200, res.text
    variants = res.json()["data"]
    assert len(variants) == 3
    listed_ids = {v["id"] for v in variants}
    assert listed_ids == set(generated_variant_ids)
    for variant_payload in variants:
        assert variant_payload["status"] == "ready"
        assert variant_payload["is_champion"] is False
        assert variant_payload["chapter_id"] == chapter_id

    # ==================================================================
    # Step 6: POST /api/v1/studio/story-variants/{id}/clone with new_archetype.
    #
    # 期望：
    #   - 新变体 ID != 源 ID 且为 32 位 hex；
    #   - status=draft / is_champion=False；
    #   - archetype 被覆盖；
    #   - 其它字段（project_id / chapter_id / script_full_text）保留。
    # ==================================================================
    source_variant_id = generated_variant_ids[0]
    source_archetype = expected_archetypes[0]
    override_archetype = "rebel-clone-override"  # 与源 archetype 必然不同

    res = client.post(
        f"/api/v1/studio/story-variants/{source_variant_id}/clone",
        json={
            "new_archetype": override_archetype,
            "label": "ab-clone",
        },
    )
    assert res.status_code == 201, res.text
    cloned = res.json()["data"]
    cloned_variant_id: str = cloned["id"]
    assert cloned_variant_id != source_variant_id
    assert len(cloned_variant_id) == 32
    assert cloned["status"] == "draft"
    assert cloned["is_champion"] is False
    assert cloned["archetype"] == override_archetype
    assert cloned["archetype"] != source_archetype
    assert cloned["project_id"] == project_id
    assert cloned["chapter_id"] == chapter_id

    # 直接 DB 读取确认 script 字段从源变体深拷贝过来。
    async with session_factory() as session:
        source_variant = (
            await session.execute(
                select(StoryVariant).where(StoryVariant.id == source_variant_id)
            )
        ).scalar_one()
        cloned_variant = (
            await session.execute(
                select(StoryVariant).where(StoryVariant.id == cloned_variant_id)
            )
        ).scalar_one()
        assert cloned_variant.script_full_text == source_variant.script_full_text
        assert cloned_variant.script_breakdown == source_variant.script_breakdown
        # 深拷贝：不是同一个对象引用。
        assert cloned_variant.script_breakdown is not source_variant.script_breakdown

    # ==================================================================
    # Step 7: PATCH /api/v1/studio/story-variants/{cloned}/champion.
    #
    # 期望：
    #   - 目标变体 is_champion=True；
    #   - 同章节其它变体 is_champion=False（命名空间内单选）。
    # ==================================================================
    res = client.patch(
        f"/api/v1/studio/story-variants/{cloned_variant_id}/champion"
    )
    assert res.status_code == 200, res.text
    champion_payload = res.json()["data"]
    assert champion_payload["id"] == cloned_variant_id
    assert champion_payload["is_champion"] is True

    # ==================================================================
    # Step 8: 最终断言：
    #   - 4 个变体在 (project_id, chapter_id) 命名空间内（3 generated + 1 clone）；
    #   - 恰好 1 个 is_champion=True；
    #   - 冠军是 step 7 标记的克隆变体。
    # ==================================================================
    res = client.get(
        f"/api/v1/studio/story-variants?project_id={project_id}"
        f"&chapter_id={chapter_id}"
    )
    assert res.status_code == 200, res.text
    final_variants = res.json()["data"]
    assert len(final_variants) == 4, (
        f"expected 4 variants in ({project_id}, {chapter_id}), "
        f"got {len(final_variants)}"
    )
    champions = [v for v in final_variants if v["is_champion"]]
    assert len(champions) == 1, (
        f"expected exactly 1 champion in ({project_id}, {chapter_id}), "
        f"got {len(champions)}"
    )
    assert champions[0]["id"] == cloned_variant_id
