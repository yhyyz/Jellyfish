"""W9-T2: 商业化（commerce_story）端到端 smoke 测试。

本测试是 P1 阶段的"完成验收闸门"：用一个 async 测试串起完整的"用户视角"
全流程，确保 W2 (DB) → W3 (seed) → W4 (agents) → W5 (workers) → W6 (HTTP
endpoints) 五条线在同一份数据库 + 同一个 FastAPI 应用上确实跑通。

为什么只写一个测试函数：
    本任务的价值在于"证明端到端可走通"，而非"覆盖每一个分支"。后者已由
    各模块单测（``test_products_api.py`` / ``test_compliance_check_worker.py``
    等）提供。把所有步骤串起来用一个 test 表达，能让 CI 在 P1 闸门崩溃
    时直接指向"流程"问题而不是"局部 bug"，与 W9 的"smoke / 闸门"定位对
    齐。

测试编排：
    1. 端到端涉及到的 ORM 必须在 ``Base.metadata.create_all`` 之前
       *全部 import 进来*（参考 ``test_alembic_commerce_migrations.py`` 与
       ``test_story_script_generate_worker.py`` 的做法），否则
       ``Base.metadata`` 会缺表。
    2. 启动期 seed（prompts / formulas / compliance）通过
       :func:`bootstrap_async_state` 一次性写入测试库；这正是 FastAPI
       lifespan 在生产上做的事，复用它能让闸门验证"启动种子链路"是
       否完整。
    3. 把 FastAPI 应用 ``get_db`` 依赖覆盖到测试 sessionmaker，让所有
       HTTP 调用都打到同一个 SQLite 文件；同时 monkeypatch worker 内
       部的 ``async_session_maker`` 与 ``story_script_generate_worker``
       的同名引用，让 worker 直接调用时也使用同一个库（这是真实部署
       下 Celery 进程与 FastAPI 进程共享 DB 的等效）。
    4. LLM 全部走 mock：``langchain_openai.ChatOpenAI`` 被替换为返回
       canned 响应的 ``BaseChatModel``，保证既不触网也不打钱。

预期结果：
    - 11 个 sub-step 全部通过；
    - 创建的 ``StoryVariant.compliance_score`` 因缺 "演绎" 字样被
      ``cn_yanyi_label`` 规则扣到 < 100，证明合规规则引擎真实运行。
"""

# pylint: disable=invalid-name,redefined-outer-name,too-many-locals,too-many-statements

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Generator
from typing import Any

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
from app.models.compliance import ComplianceFinding
from app.models.llm import (
    Model,
    ModelCategoryKey,
    ModelSettings,
    Provider,
)
from app.models.story_formula import StoryVariant
from app.models.studio import Chapter
from app.models.types import (
    ChapterStatus,
    ProductCategory,
    ProjectKind,
    ProjectStyle,
    ProjectVisualStyle,
)
from app.services.commerce.compliance_check_worker import run_compliance_check_task
from app.services.commerce.story_script_generate_worker import (
    run_story_script_generate_task,
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
        return "mock-e2e-smoke-chat-model"

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


def _empty_compliance_report_json() -> str:
    """LLM 端返回"未发现风险"的 ComplianceReport JSON（规则引擎仍会跑）。"""
    return json.dumps(
        {
            "variant_id": None,
            "region": "cn_mainland",
            "product_category": "other",
            "findings": [],
            "score": 100,
            "summary": "未发现合规风险。",
        }
    )


def _canned_story_script_dict() -> dict[str, Any]:
    """供 StoryScriptGeneratorAgent 在 mock 路径中返回的 StoryScript 模型 dump。

    刻意省略 "演绎/虚构" 字样：让后续合规检查（步骤 9）能命中规则引擎
    的 ``cn_yanyi_label`` blocker，从而验证 ``compliance_score < 100``。
    """
    per_shot = 60 / 4
    return {
        "total_duration_sec": 60,
        "total_shots": 4,
        "formula_id": "underdog_triumph",
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

    db_path = tmp_path / "commerce-e2e-smoke.db"
    engine: AsyncEngine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}", future=True
    )
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 跑全套 bootstrap：写入 27 条 prompt + 6 条 cn 公式 + 8 条合规规则。
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
    """直接 DB 写一条 Chapter（路径一：API 没有暴露 commerce_story 项目下的
    chapter create endpoint，按任务说明手动 seed）。"""
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
# 2) The single "P1 done" gate test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commerce_full_user_journey_smoke(  # noqa: PLR0915
    session_factory: async_sessionmaker[AsyncSession],
    client_with_db: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """全链路 smoke：商品 → 公式 → 项目 → 挂载 → 生成 → 合规 → 查询。

    11 个 sub-step 一次性串起来；任何一步红就证明 P1 闸门未达成。
    """

    # ------------------------------------------------------------------
    # Mock LLM 路径：worker 入口会调用 build_default_text_llm{,_sync}，
    # 它内部 import ``langchain_openai.ChatOpenAI``。我们把它替换成"返回
    # mock chat model"，使两个 worker 不实际触网。
    # ------------------------------------------------------------------
    compliance_llm_response = _empty_compliance_report_json()

    def _factory_chat_openai(**_kwargs: Any) -> BaseChatModel:
        # 同一个 mock 在两个 worker 中都会被调用；不同 worker 期望的
        # JSON 形态不同，但 StoryScriptGeneratorAgent 在测试中我们
        # 通过 monkeypatch 直接替掉 ``a_generate_script``，因此 mock 的
        # 字符串内容只对 ComplianceCheckerAgent 生效。
        return _MockChatModel(compliance_llm_response)

    monkeypatch.setattr("langchain_openai.ChatOpenAI", _factory_chat_openai)

    # 直接替掉 StoryScriptGeneratorAgent 的 a_generate_script，让其
    # 返回 canned StoryScript（不经过任何 LangChain JSON 解析路径，
    # 因为脚本协议较复杂，mock 单一字符串容易触发结构校验失败）。
    canned_dict = _canned_story_script_dict()

    async def _mock_a_generate_script(
        self: Any,  # noqa: ARG001  pylint: disable=unused-argument
        *,
        vars: Any,  # noqa: ARG001  pylint: disable=redefined-builtin,unused-argument
    ) -> Any:
        from app.core.contracts.story import StoryScript  # 局部 import 防循环

        return StoryScript.model_validate(canned_dict)

    monkeypatch.setattr(
        "app.chains.agents.commerce.story_script_generator_agent."
        "StoryScriptGeneratorAgent.a_generate_script",
        _mock_a_generate_script,
    )

    # 让 worker 内部 ``async_session_maker`` 也指向测试库。FastAPI 依赖
    # 已经被 ``client_with_db`` fixture 覆盖了，但 worker 是直接 ``await``
    # 调用、不走依赖注入，因此必须显式 monkeypatch。
    monkeypatch.setattr(
        "app.services.commerce.compliance_check_worker.async_session_maker",
        session_factory,
    )

    client = client_with_db

    # ==================================================================
    # Step 1: POST /api/v1/studio/products
    # ==================================================================
    create_product_body = {
        "name": "维生素 C 精华液",
        "brand": "Acme",
        "category": ProductCategory.other.value,
        "description": "提亮肤色，焕活光彩",
        "selling_points": ["7 天见效", "敏感肌可用"],
        "target_audience": {"age_range": "25-35"},
        "catchphrases": ["你也值得"],
        "competitor_names": ["竞品 X"],
        "visual_style": ProjectVisualStyle.live_action.value,
        "style": ProjectStyle.real_people_city.value,
    }
    res = client.post("/api/v1/studio/products", json=create_product_body)
    assert res.status_code == 201, res.text
    product_payload = res.json()["data"]
    product_id = product_payload["id"]
    assert isinstance(product_id, str) and product_id, "expected non-empty product id"
    assert product_payload["name"] == create_product_body["name"]

    # ==================================================================
    # Step 2: GET /api/v1/studio/story-formulas (cn region must have ≥6)
    # ==================================================================
    res = client.get("/api/v1/studio/story-formulas?region=cn")
    assert res.status_code == 200, res.text
    formulas = res.json()["data"]
    assert len(formulas) >= 6, f"expected ≥6 cn formulas from bootstrap, got {len(formulas)}"
    formula_ids = {f["id"] for f in formulas}
    # bootstrap_builtin_story_formulas 至少要写入这 6 条。
    expected_subset = {
        "underdog_triumph",
        "contrast_surprise",
        "workplace_hero",
        "family_conflict",
        "mystery_twist",
        "time_travel",
    }
    assert expected_subset.issubset(formula_ids), (
        f"missing built-in formulas; want {expected_subset}, got {formula_ids}"
    )
    formula_id = "underdog_triumph"

    # ==================================================================
    # Step 3: 直接 DB seed Chapter（commerce_story 项目目前没有公开的
    # chapter 创建路径，按任务说明手动 seed）
    # ==================================================================
    project_id = "sp_e2e_1"
    chapter_id = "chap_e2e_1"
    # 顺序：必须先创建 Project（step 4）再写 Chapter，因为 chapter.project_id
    # 有外键。但为了让 step 4 创建项目时已知 chapter_id 与 project_id，
    # 这里只准备 ID，待 step 4 执行后立即在 step 4 之后 seed。

    # ==================================================================
    # Step 4: POST /api/v1/studio/story-projects
    # ==================================================================
    create_project_body = {
        "id": project_id,
        "name": "维生素 C 带货项目",
        "description": "P1 smoke 项目",
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
    assert project_data["config"]["formula_id"] == formula_id
    assert project_data["config"]["compliance_region"] == "cn_mainland"

    # 项目落库后再 seed Chapter（chapter.project_id 外键依赖项目存在）。
    await _seed_chapter(session_factory, project_id, chapter_id)

    # ==================================================================
    # Step 5: POST /api/v1/studio/story-projects/{id}/products/{pid}
    # ==================================================================
    res = client.post(
        f"/api/v1/studio/story-projects/{project_id}/products/{product_id}",
        json={
            "role_in_story": "savior",
            "appearance_timing": "middle",
            "appearance_duration_sec": 8,
        },
    )
    assert res.status_code == 201, res.text
    link_data = res.json()["data"]
    assert link_data["project_id"] == project_id
    assert link_data["product_id"] == product_id
    assert link_data["appearance_duration_sec"] == 8

    # ==================================================================
    # Step 6: GET /api/v1/studio/story-projects/{id} —— 验证项目已落库
    # 且与 step 4 一致；P1 阶段 detail 返回不含 products 字段，单独通过
    # 列表/详情 endpoint 验证项目自身存在已经足够，product 挂载关系由
    # step 5 的 201 + 该 link record 保证。
    # ==================================================================
    res = client.get(f"/api/v1/studio/story-projects/{project_id}")
    assert res.status_code == 200, res.text
    detail = res.json()["data"]
    assert detail["id"] == project_id
    assert detail["config"]["target_duration_sec"] == 60

    # ==================================================================
    # Step 7: 直接 await run_story_script_generate_task（W5-T2）
    # ==================================================================
    script_runner_args: dict[str, Any] = {
        "project_id": project_id,
        "chapter_id": chapter_id,
        "formula_id": formula_id,
        "formula": {"id": formula_id, "beats": ["hook", "reveal", "cta"]},
        "product": {
            "name": create_product_body["name"],
            "brand": create_product_body["brand"],
            "category": ProductCategory.other.value,
        },
        "audience": {"persona": "office_worker", "pain": "dull_skin"},
        "archetype": "sage",
        "tone_grid": {"formality": 0.3, "energy": 0.7},
        "target_duration_sec": 60,
        "platform": "douyin",
    }
    script_output = await run_story_script_generate_task(
        "task-script-1",
        script_runner_args,
        session_factory=session_factory,
    )
    assert "variant_id" in script_output
    variant_id: str = script_output["variant_id"]
    assert isinstance(variant_id, str) and variant_id

    # 直接读 DB 断言变体落库 + status=ready。
    async with session_factory() as session:
        variant = (
            await session.execute(
                select(StoryVariant).where(StoryVariant.id == variant_id)
            )
        ).scalar_one()
        assert variant.project_id == project_id
        assert variant.chapter_id == chapter_id
        assert variant.formula_id == formula_id
        assert variant.status == "ready", (
            f"expected variant.status=ready after generation, got {variant.status}"
        )
        assert variant.compliance_score == 0  # W5-T2 不写分

    # ==================================================================
    # Step 8: GET /api/v1/studio/story-variants?project_id=...
    # ==================================================================
    res = client.get(
        f"/api/v1/studio/story-variants?project_id={project_id}"
    )
    assert res.status_code == 200, res.text
    variants = res.json()["data"]
    assert len(variants) == 1
    assert variants[0]["id"] == variant_id
    assert variants[0]["status"] == "ready"

    # ==================================================================
    # Step 9: 直接 await run_compliance_check_task（W5-T3）
    # 故意传入缺 "演绎/虚构" 的脚本：LLM 端返回 0 finding，但规则引擎
    # 真实命中 cn_yanyi_label blocker，让 compliance_score < 100。
    # ==================================================================
    no_yanyi_script = "今天给大家推荐一款产品，效果非常好。"
    await run_compliance_check_task(
        "task-compliance-1",
        {
            "variant_id": variant_id,
            "region": "cn_mainland",
            "product_category": "other",
            "script_text": no_yanyi_script,
            "script_duration_sec": 60,
        },
    )

    async with session_factory() as session:
        finding_rows = list(
            (
                await session.execute(
                    select(ComplianceFinding).where(
                        ComplianceFinding.variant_id == variant_id
                    )
                )
            ).scalars().all()
        )
        assert finding_rows, "compliance check should have persisted ≥1 finding"
        rule_ids = {row.rule_id for row in finding_rows}
        assert "cn_yanyi_label" in rule_ids, (
            f"expected cn_yanyi_label blocker in findings, got {rule_ids}"
        )
        # variant.compliance_score 已经被 worker 更新。
        refreshed = (
            await session.execute(
                select(StoryVariant).where(StoryVariant.id == variant_id)
            )
        ).scalar_one()
        score_after_check = refreshed.compliance_score

    # ==================================================================
    # Step 10: GET /api/v1/studio/compliance/findings?variant_id=...
    # ==================================================================
    res = client.get(
        f"/api/v1/studio/compliance/findings?variant_id={variant_id}"
    )
    assert res.status_code == 200, res.text
    api_findings = res.json()["data"]
    assert len(api_findings) >= 1
    api_rule_ids = {f["rule_id"] for f in api_findings}
    assert "cn_yanyi_label" in api_rule_ids

    # ==================================================================
    # Step 11: 最终断言 —— compliance_score < 100
    # ==================================================================
    assert score_after_check < 100, (
        f"expected compliance_score < 100 because of yanyi blocker, "
        f"got {score_after_check}"
    )
