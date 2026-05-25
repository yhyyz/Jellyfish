"""W12-T4: ``cta_writer`` worker 执行器测试。

测试策略（与 W5-T3 ``test_compliance_check_worker.py`` 同构）：
    - 使用真实 SQLite (file-backed) + ``Base.metadata.create_all`` 建表，
      让 ``story_variants`` 走完整 ORM 路径；
    - ``langchain_openai.ChatOpenAI`` 在 worker 路径上 monkeypatch 成
      返回固定 :class:`CTAText` JSON 的 ``BaseChatModel``，避免触网；
    - **不**替换 :class:`CTAWriterAgent`：本任务的集成价值就是 worker
      正确把 :class:`CTAWriteVars` 喂给 Agent，并把回写到 variant 上的
      字段限制在 ``cta_text``，mock 掉就失去意义；
    - 验证项分四类：DB in-place patch、output payload、入参校验、注册表对接。
"""

# pylint: disable=protected-access,too-few-public-methods,redefined-outer-name

from __future__ import annotations

import json
from typing import Any

import pytest
import pytest_asyncio
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.core.task_manager import SqlAlchemyTaskStore
from app.core.task_manager.types import DeliveryMode
from app.models.story_formula import StoryFormula, StoryVariant
from app.models.studio import Chapter, Project
from app.models.studio_prompts_files_timeline import PromptTemplate
from app.models.task import GenerationTask, GenerationTaskStatus
from app.models.types import (
    ProjectStyle,
    PromptCategory,
)
from app.services.commerce.cta_writer_worker import (
    DEFAULT_TIMEOUT_SEC,
    TASK_KIND,
    build_cta_writer_executor,
    run_cta_writer_task,
)
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_registry import task_executor_registry


# ---------------------------------------------------------------------------
# 共用 LLM mock & CTAText JSON 构造工具
# ---------------------------------------------------------------------------


class _MockChatModel(BaseChatModel):
    """LangChain ``BaseChatModel`` 的最小可用桩：恒定返回一段字符串。"""

    response: str = ""

    def __init__(self, response: str = "", **_kwargs: Any) -> None:
        super().__init__()
        object.__setattr__(self, "response", response)

    @property
    def _llm_type(self) -> str:  # pragma: no cover - LangChain 协议要求
        return "mock-cta-writer-chat-model"

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


def _cta_json(
    *,
    cta_text: str = "限时8折，点击下方加购！",
    pattern_id: str = "scarcity_001",
    hardness: str = "medium",
    urgency_type: str = "scarcity",
    rationale: str | None = "强稀缺性触发购买决策",
) -> str:
    """构造一个合法的 :class:`CTAText` JSON 字符串供 mock LLM 返回。"""
    payload: dict[str, Any] = {
        "cta_text": cta_text,
        "pattern_id": pattern_id,
        "hardness": hardness,
        "urgency_type": urgency_type,
        "rationale": rationale,
    }
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 共用 fixture：file-backed SQLite + Provider/Model + StoryVariant
# ---------------------------------------------------------------------------


async def _seed_provider_and_model(db: AsyncSession) -> None:
    """补齐 ``build_default_text_llm_sync`` 所需的 Provider + Model + ModelSettings。"""

    # pylint: disable=import-outside-toplevel
    from app.models.llm import Model, ModelCategoryKey, ModelSettings, Provider

    db.add(
        Provider(
            id="prov-1",
            name="MockProvider",
            base_url="http://example.invalid",
            api_key="sk-test",
        )
    )
    db.add(
        Model(
            id="model-1",
            provider_id="prov-1",
            name="mock-text-model",
            category=ModelCategoryKey.text,
            params={},
        )
    )
    db.add(
        ModelSettings(
            id=1,
            default_text_model_id="model-1",
            default_image_model_id=None,
            default_video_model_id=None,
        )
    )
    await db.flush()


_DEFAULT_BREAKDOWN: dict[str, Any] = {
    "opening_hook": "原始钩子，应保持不变",
    "cta_text": "原始 CTA，应被改写",
    "shots": [{"id": "shot_001", "function": "hook"}],
    "total_shots": 1,
}


async def _seed_variant(
    db: AsyncSession,
    *,
    variant_id: str = "var-test",
    script_breakdown: dict[str, Any] | None = None,
) -> None:
    """种入 Project / Chapter / PromptTemplate / StoryFormula / StoryVariant。"""

    db.add(Project(id="proj-1", name="测试项目", style=ProjectStyle.real_people_city))
    db.add(Chapter(id="chap-1", project_id="proj-1", index=1, title="第 1 章"))
    db.add(
        PromptTemplate(
            id="tpl-1",
            category=PromptCategory.video_prompt,
            name="占位模板",
            content="...",
        )
    )
    db.add(StoryFormula(id="formula-1", name="测试公式", prompt_template_id="tpl-1"))
    db.add(
        StoryVariant(
            id=variant_id,
            project_id="proj-1",
            chapter_id="chap-1",
            formula_id="formula-1",
            script_breakdown=(
                script_breakdown if script_breakdown is not None else dict(_DEFAULT_BREAKDOWN)
            ),
        )
    )
    await db.flush()


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    """构造一个 file-backed SQLite 引擎并返回 ``async_sessionmaker``。"""

    db_path = tmp_path / "cta-writer-worker.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield session_local
    await engine.dispose()


def _patch_session_maker(monkeypatch: pytest.MonkeyPatch, session_local: Any) -> None:
    """让 worker 内部的 ``async_session_maker`` 指向测试 ``session_local``。"""

    monkeypatch.setattr(
        "app.services.commerce.cta_writer_worker.async_session_maker",
        session_local,
    )


def _patch_chat_openai(monkeypatch: pytest.MonkeyPatch, llm: BaseChatModel) -> None:
    """把 ``langchain_openai.ChatOpenAI`` 替换成 ``lambda **_: llm``。"""

    monkeypatch.setattr("langchain_openai.ChatOpenAI", lambda **_kwargs: llm)


async def _create_task(session_local: Any, *, run_args: dict[str, Any]) -> str:
    """在测试 DB 里建一条 ``GenerationTask`` 并返回 task_id。"""

    async with session_local() as db:
        store = SqlAlchemyTaskStore(db)
        task = await store.create(
            payload={"task_kind": TASK_KIND, "run_args": run_args},
            mode=DeliveryMode.async_polling,
            task_kind=TASK_KIND,
        )
        await db.commit()
        return task.id


def _base_run_args(**overrides: Any) -> dict[str, Any]:
    """合法的最小 run_args 集合，可由测试通过 kwargs 覆盖单字段。"""
    args: dict[str, Any] = {
        "variant_id": "var-1",
        "pattern_id": "scarcity_001",
        "hardness": "medium",
        "urgency_type": "scarcity",
        "product_name": "Vitamin C Serum",
        "product_url": "https://shop.example.com/p/vc-serum",
        "discount_text": "限时8折",
        "target_action": "加购",
    }
    args.update(overrides)
    return args


# ---------------------------------------------------------------------------
# 1. 入参校验
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_validates_required_variant_id(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``variant_id`` 缺失/为空 → ValueError。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(db, variant_id="var-1")
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(monkeypatch, _MockChatModel(_cta_json()))

    run_args = _base_run_args(variant_id="")
    task_id = await _create_task(session_local, run_args=run_args)
    with pytest.raises(ValueError, match="variant_id"):
        await run_cta_writer_task(task_id, run_args)


@pytest.mark.asyncio
async def test_runner_validates_required_pattern_id(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``pattern_id`` 缺失/为空 → ValueError。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(db, variant_id="var-1")
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(monkeypatch, _MockChatModel(_cta_json()))

    run_args = _base_run_args(pattern_id="")
    task_id = await _create_task(session_local, run_args=run_args)
    with pytest.raises(ValueError, match="pattern_id"):
        await run_cta_writer_task(task_id, run_args)


# ---------------------------------------------------------------------------
# 2. 持久化：原地 patch cta_text
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_patches_variant_cta_text(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLM 返回的 cta_text 必须落到 variant.script_breakdown['cta_text']。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(db, variant_id="var-1")
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(
        monkeypatch,
        _MockChatModel(_cta_json(cta_text="今天下单，立省 ¥100！")),
    )

    run_args = _base_run_args()
    task_id = await _create_task(session_local, run_args=run_args)
    await run_cta_writer_task(task_id, run_args)

    async with session_local() as db:
        variant = await db.get(StoryVariant, "var-1")
    assert variant is not None
    breakdown = variant.script_breakdown or {}
    assert breakdown.get("cta_text") == "今天下单，立省 ¥100！"


# ---------------------------------------------------------------------------
# 3. result payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_returns_cta_text_in_result(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """task.result 必须暴露 cta_text + pattern 元数据 + variant_id。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(db, variant_id="var-1")
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(
        monkeypatch,
        _MockChatModel(
            _cta_json(
                cta_text="今天下单，立省 ¥100！",
                pattern_id="scarcity_001",
                hardness="hard",
                urgency_type="urgency",
            )
        ),
    )

    run_args = _base_run_args(hardness="hard", urgency_type="urgency")
    task_id = await _create_task(session_local, run_args=run_args)
    await run_cta_writer_task(task_id, run_args)

    async with session_local() as db:
        task = await db.get(GenerationTask, task_id)
    assert task is not None
    result = task.result or {}
    assert result.get("variant_id") == "var-1"
    assert result.get("cta_text") == "今天下单，立省 ¥100！"
    assert result.get("pattern_id") == "scarcity_001"
    assert result.get("hardness") == "hard"
    assert result.get("urgency_type") == "urgency"


# ---------------------------------------------------------------------------
# 4. 失败路径：Agent 抛错
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_marks_failed_on_agent_error(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLM 返回非 JSON → format_output 失败 → task 状态 failed + 抛错。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(db, variant_id="var-1")
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(monkeypatch, _MockChatModel("totally invalid response"))

    run_args = _base_run_args()
    task_id = await _create_task(session_local, run_args=run_args)
    with pytest.raises(Exception):  # noqa: B017
        await run_cta_writer_task(task_id, run_args)

    async with session_local() as db:
        task = await db.get(GenerationTask, task_id)
    assert task is not None
    assert task.status == GenerationTaskStatus.failed
    assert task.error


# ---------------------------------------------------------------------------
# 5. 缺失 variant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_handles_missing_variant_404(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``variant_id`` 在 DB 中不存在 → task failed，error 提示找不到。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(monkeypatch, _MockChatModel(_cta_json()))

    run_args = _base_run_args(variant_id="not-exists")
    task_id = await _create_task(session_local, run_args=run_args)
    with pytest.raises(ValueError, match="StoryVariant not found"):
        await run_cta_writer_task(task_id, run_args)

    async with session_local() as db:
        task = await db.get(GenerationTask, task_id)
    assert task is not None
    assert task.status == GenerationTaskStatus.failed


# ---------------------------------------------------------------------------
# 6. 注册表 / 配置常量
# ---------------------------------------------------------------------------


def test_executor_registered_with_correct_task_kind() -> None:
    """task_executor_registry 解析 ``cta_writer`` → AbstractAsyncDelegatingExecutor。"""

    executor = task_executor_registry.resolve(TASK_KIND)
    assert isinstance(executor, AbstractAsyncDelegatingExecutor)
    assert executor.task_kind == TASK_KIND


def test_executor_timeout_set_to_120s() -> None:
    """注册时使用 ``DEFAULT_TIMEOUT_SEC`` (120s) 作为默认超时。"""

    executor = build_cta_writer_executor()
    assert executor.timeout_seconds == DEFAULT_TIMEOUT_SEC == 120.0
    assert executor.task_kind == TASK_KIND


# ---------------------------------------------------------------------------
# 7. 仅改 cta_text，不动其它字段
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_preserves_other_breakdown_fields(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """patch 仅更新 cta_text；opening_hook / shots / 其他字段必须保持原值。"""

    session_local = session_factory
    initial = {
        "opening_hook": "ORIGINAL HOOK",
        "cta_text": "ORIGINAL CTA",
        "shots": [{"id": "shot_001", "function": "hook"}, {"id": "shot_002"}],
        "total_shots": 2,
        "brand_mention_count": 1,
    }
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(db, variant_id="var-1", script_breakdown=initial)
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(
        monkeypatch, _MockChatModel(_cta_json(cta_text="REWRITTEN CTA"))
    )

    run_args = _base_run_args()
    task_id = await _create_task(session_local, run_args=run_args)
    await run_cta_writer_task(task_id, run_args)

    async with session_local() as db:
        variant = await db.get(StoryVariant, "var-1")
    assert variant is not None
    breakdown = variant.script_breakdown or {}
    assert breakdown["cta_text"] == "REWRITTEN CTA"
    # 其他字段一字不改
    assert breakdown["opening_hook"] == "ORIGINAL HOOK"
    assert breakdown["shots"] == initial["shots"]
    assert breakdown["total_shots"] == 2
    assert breakdown["brand_mention_count"] == 1


# ---------------------------------------------------------------------------
# 8. 透传：完整 vars 喂给 Agent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_passes_full_vars_to_agent(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_args 中的全部字段必须以 ``CTAWriteVars`` 形式透传给 Agent。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(db, variant_id="var-1")
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(monkeypatch, _MockChatModel(_cta_json()))

    captured: dict[str, Any] = {}

    # pylint: disable=import-outside-toplevel
    from app.services.commerce import cta_writer_worker as worker_mod

    real_a_write_cta = worker_mod.CTAWriterAgent.a_write_cta  # type: ignore[attr-defined]

    async def _spy_a_write_cta(  # noqa: ANN001,A002
        self: Any,
        *,
        vars: Any,  # pylint: disable=redefined-builtin
    ):
        captured["vars"] = vars
        return await real_a_write_cta(self, vars=vars)

    monkeypatch.setattr(
        "app.services.commerce.cta_writer_worker.CTAWriterAgent.a_write_cta",
        _spy_a_write_cta,
    )

    run_args = _base_run_args(
        product_url="https://shop.example.com/p/vc",
        discount_text="限时8折",
        target_action="下单",
    )
    task_id = await _create_task(session_local, run_args=run_args)
    await run_cta_writer_task(task_id, run_args)

    captured_vars = captured.get("vars")
    assert captured_vars is not None
    assert captured_vars.pattern_id == "scarcity_001"
    assert captured_vars.hardness == "medium"
    assert captured_vars.urgency_type == "scarcity"
    assert captured_vars.product_name == "Vitamin C Serum"
    assert captured_vars.product_url == "https://shop.example.com/p/vc"
    assert captured_vars.discount_text == "限时8折"
    assert captured_vars.target_action == "下单"


# ---------------------------------------------------------------------------
# 9. target_action 缺省回退 + optional 字段透传 None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_defaults_target_action_when_omitted(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``target_action`` 缺省时回退到 "加购"，与 :class:`CTAWriteVars` 默认一致。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(db, variant_id="var-1")
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(monkeypatch, _MockChatModel(_cta_json()))

    captured: dict[str, Any] = {}

    # pylint: disable=import-outside-toplevel
    from app.services.commerce import cta_writer_worker as worker_mod

    real_a_write_cta = worker_mod.CTAWriterAgent.a_write_cta  # type: ignore[attr-defined]

    async def _spy_a_write_cta(  # noqa: ANN001,A002
        self: Any,
        *,
        vars: Any,  # pylint: disable=redefined-builtin
    ):
        captured["vars"] = vars
        return await real_a_write_cta(self, vars=vars)

    monkeypatch.setattr(
        "app.services.commerce.cta_writer_worker.CTAWriterAgent.a_write_cta",
        _spy_a_write_cta,
    )

    run_args = _base_run_args()
    run_args.pop("target_action")
    run_args["product_url"] = None
    run_args["discount_text"] = None
    task_id = await _create_task(session_local, run_args=run_args)
    await run_cta_writer_task(task_id, run_args)

    captured_vars = captured.get("vars")
    assert captured_vars is not None
    assert captured_vars.target_action == "加购"
    assert captured_vars.product_url is None
    assert captured_vars.discount_text is None


# ---------------------------------------------------------------------------
# 10. 任务状态推进
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_marks_task_succeeded_on_happy_path(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """成功路径下 task.status 推进到 succeeded，progress=100。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(db, variant_id="var-1")
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(monkeypatch, _MockChatModel(_cta_json()))

    run_args = _base_run_args()
    task_id = await _create_task(session_local, run_args=run_args)
    await run_cta_writer_task(task_id, run_args)

    async with session_local() as db:
        task = await db.get(GenerationTask, task_id)
    assert task is not None
    assert task.status == GenerationTaskStatus.succeeded
    assert task.progress == 100
