"""W12-T4: ``archetype_rewrite`` worker 执行器测试。

测试策略（与 W5-T3 ``test_compliance_check_worker.py`` 同构）：
    - 使用真实 SQLite (file-backed) + ``Base.metadata.create_all`` 建表，
      让 ``story_variants`` 走完整 ORM 路径；
    - ``langchain_openai.ChatOpenAI`` 在 worker 路径上 monkeypatch 成
      返回固定 :class:`StoryScript` JSON 的 ``BaseChatModel``，避免触网；
    - **不**替换 :class:`ArchetypeVoiceRewriterAgent`：本任务的集成价值
      就是 worker 正确把脚本喂进去并把改写结果整段写回 variant，
      mock 掉就失去意义；同时 Agent 内置的结构保留 / 禁词校验
      也通过本测试一并覆盖；
    - 验证项分四类：DB 整段重写、archetype 列刷新、入参校验、结构校验失败。
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

from app.core.contracts.story import Shot, StoryScript
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
from app.services.commerce.archetype_rewrite_worker import (
    DEFAULT_TIMEOUT_SEC,
    TASK_KIND,
    build_archetype_rewrite_executor,
    run_archetype_rewrite_task,
)
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_registry import task_executor_registry


# ---------------------------------------------------------------------------
# 共用 LLM mock & StoryScript JSON 构造工具
# ---------------------------------------------------------------------------


class _MockChatModel(BaseChatModel):
    """LangChain ``BaseChatModel`` 的最小可用桩：恒定返回一段字符串。"""

    response: str = ""

    def __init__(self, response: str = "", **_kwargs: Any) -> None:
        super().__init__()
        object.__setattr__(self, "response", response)

    @property
    def _llm_type(self) -> str:  # pragma: no cover - LangChain 协议要求
        return "mock-archetype-rewrite-chat-model"

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


def _make_shot(
    *,
    shot_id: str,
    dialog: str | None = "原始对白",
    narration: str | None = None,
    is_brand_mention: bool = False,
) -> Shot:
    """构造合法 :class:`Shot`；仅暴露关键差异，其它字段使用稳定占位值。"""
    return Shot(
        id=shot_id,
        duration_sec=5.0,
        function="generic",
        shot_type="medium",
        camera_angle="eye_level",
        camera_movement="static",
        dialog=dialog,
        narration=narration,
        product_focus_level="none",
        is_punchline=False,
        is_brand_mention=is_brand_mention,
        notes=None,
    )


def _make_original_script() -> StoryScript:
    """4 镜原始脚本，含 1 条品牌口播位，供改写基准与 LLM 输出共同使用。"""
    return StoryScript(
        total_duration_sec=20.0,
        total_shots=4,
        formula_id="dramatic_reversal",
        shots=[
            _make_shot(shot_id="shot_001", dialog="原始对白 1"),
            _make_shot(shot_id="shot_002", dialog="原始对白 2"),
            _make_shot(shot_id="shot_003", dialog="原始对白 3", is_brand_mention=True),
            _make_shot(shot_id="shot_004", dialog="原始对白 4"),
        ],
        opening_hook="原始钩子",
        cta_text="原始 CTA",
        brand_mention_count=1,
    )


def _make_rewritten_script_dict(
    *,
    dialog_prefix: str = "改写后",
    opening_hook: str = "改写后的钩子",
    cta_text: str = "改写后的 CTA",
) -> dict[str, Any]:
    """构造一份**保留结构**的改写脚本 dict，供 mock LLM 返回。

    保留每个 shot 的 ``id`` / ``duration_sec`` / ``shot_type`` /
    ``camera_angle`` / ``camera_movement`` / ``is_brand_mention``，
    只改写文本字段。这样 ``ArchetypeVoiceRewriterAgent`` 内置的
    ``validate_structure_preserved`` 与 ``validate_words_to_avoid``
    都能通过，确保 worker 走到持久化路径。
    """
    rewritten = StoryScript(
        total_duration_sec=20.0,
        total_shots=4,
        formula_id="dramatic_reversal",
        shots=[
            _make_shot(shot_id="shot_001", dialog=f"{dialog_prefix} 1"),
            _make_shot(shot_id="shot_002", dialog=f"{dialog_prefix} 2"),
            _make_shot(
                shot_id="shot_003",
                dialog=f"{dialog_prefix} 3",
                is_brand_mention=True,
            ),
            _make_shot(shot_id="shot_004", dialog=f"{dialog_prefix} 4"),
        ],
        opening_hook=opening_hook,
        cta_text=cta_text,
        brand_mention_count=1,
    )
    return rewritten.model_dump(mode="json")


def _make_structure_broken_script_dict() -> dict[str, Any]:
    """构造一份**结构被破坏**的改写脚本 dict（少一镜），用于触发 validator。"""
    rewritten = StoryScript(
        total_duration_sec=15.0,
        total_shots=3,
        formula_id="dramatic_reversal",
        shots=[
            _make_shot(shot_id="shot_001", dialog="改写 1"),
            _make_shot(shot_id="shot_002", dialog="改写 2"),
            _make_shot(
                shot_id="shot_003",
                dialog="改写 3",
                is_brand_mention=True,
            ),
        ],
        opening_hook="新钩子",
        cta_text="新 CTA",
        brand_mention_count=1,
    )
    return rewritten.model_dump(mode="json")


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


async def _seed_variant(
    db: AsyncSession,
    *,
    variant_id: str = "var-test",
    script_breakdown: dict[str, Any] | None = None,
) -> None:
    """种入 Project / Chapter / PromptTemplate / StoryFormula / StoryVariant。

    默认 ``script_breakdown`` 取自 :func:`_make_original_script`，
    保证 worker 入口能从 ``variant.script_breakdown`` 还原出
    合法的 :class:`StoryScript`。
    """

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
    breakdown = (
        script_breakdown
        if script_breakdown is not None
        else _make_original_script().model_dump(mode="json")
    )
    db.add(
        StoryVariant(
            id=variant_id,
            project_id="proj-1",
            chapter_id="chap-1",
            formula_id="formula-1",
            script_breakdown=breakdown,
        )
    )
    await db.flush()


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    """构造一个 file-backed SQLite 引擎并返回 ``async_sessionmaker``。"""

    db_path = tmp_path / "archetype-rewrite-worker.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield session_local
    await engine.dispose()


def _patch_session_maker(monkeypatch: pytest.MonkeyPatch, session_local: Any) -> None:
    """让 worker 内部的 ``async_session_maker`` 指向测试 ``session_local``。"""

    monkeypatch.setattr(
        "app.services.commerce.archetype_rewrite_worker.async_session_maker",
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
        "archetype": "sage",
        "archetype_description": "智者人格：理性、富有洞察、善于以知识引导",
        "tone_grid": {"formality": 7, "humanity": 6, "humor": 3},
        "words_to_avoid": ["最强"],
        "preferred_vocab": ["科学", "数据"],
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
    _patch_chat_openai(
        monkeypatch,
        _MockChatModel(json.dumps(_make_rewritten_script_dict(), ensure_ascii=False)),
    )

    run_args = _base_run_args(variant_id="")
    task_id = await _create_task(session_local, run_args=run_args)
    with pytest.raises(ValueError, match="variant_id"):
        await run_archetype_rewrite_task(task_id, run_args)


@pytest.mark.asyncio
async def test_runner_validates_required_archetype(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``archetype`` 缺失/为空 → ValueError。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(db, variant_id="var-1")
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(
        monkeypatch,
        _MockChatModel(json.dumps(_make_rewritten_script_dict(), ensure_ascii=False)),
    )

    run_args = _base_run_args(archetype="")
    task_id = await _create_task(session_local, run_args=run_args)
    with pytest.raises(ValueError, match="archetype"):
        await run_archetype_rewrite_task(task_id, run_args)


# ---------------------------------------------------------------------------
# 2. 持久化：整段替换 script_breakdown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_replaces_full_script_breakdown(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """改写后 variant.script_breakdown 必须等于 LLM 返回的 dump 整体。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(db, variant_id="var-1")
        await db.commit()

    rewritten_dict = _make_rewritten_script_dict(
        dialog_prefix="智者口吻",
        opening_hook="改写后的钩子",
        cta_text="改写后的 CTA",
    )
    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(
        monkeypatch,
        _MockChatModel(json.dumps(rewritten_dict, ensure_ascii=False)),
    )

    run_args = _base_run_args()
    task_id = await _create_task(session_local, run_args=run_args)
    await run_archetype_rewrite_task(task_id, run_args)

    async with session_local() as db:
        variant = await db.get(StoryVariant, "var-1")
    assert variant is not None
    breakdown = variant.script_breakdown or {}
    assert breakdown.get("opening_hook") == "改写后的钩子"
    assert breakdown.get("cta_text") == "改写后的 CTA"
    # 4 镜全部覆盖
    dialogs = [s["dialog"] for s in breakdown["shots"]]
    assert dialogs == [
        "智者口吻 1",
        "智者口吻 2",
        "智者口吻 3",
        "智者口吻 4",
    ]


# ---------------------------------------------------------------------------
# 3. archetype 列刷新
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_persists_archetype_on_variant(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """成功路径下 ``StoryVariant.archetype`` 必须等于 run_args.archetype。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(db, variant_id="var-1")
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(
        monkeypatch,
        _MockChatModel(json.dumps(_make_rewritten_script_dict(), ensure_ascii=False)),
    )

    run_args = _base_run_args(archetype="rebel")
    task_id = await _create_task(session_local, run_args=run_args)
    await run_archetype_rewrite_task(task_id, run_args)

    async with session_local() as db:
        variant = await db.get(StoryVariant, "var-1")
    assert variant is not None
    assert variant.archetype == "rebel"


# ---------------------------------------------------------------------------
# 4. result payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_returns_archetype_payload_in_result(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """task.result 必须暴露 variant_id / archetype / shot_count / brand_mention_count。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(db, variant_id="var-1")
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(
        monkeypatch,
        _MockChatModel(json.dumps(_make_rewritten_script_dict(), ensure_ascii=False)),
    )

    run_args = _base_run_args()
    task_id = await _create_task(session_local, run_args=run_args)
    await run_archetype_rewrite_task(task_id, run_args)

    async with session_local() as db:
        task = await db.get(GenerationTask, task_id)
    assert task is not None
    result = task.result or {}
    assert result.get("variant_id") == "var-1"
    assert result.get("archetype") == "sage"
    assert result.get("shot_count") == 4
    assert result.get("brand_mention_count") == 1


# ---------------------------------------------------------------------------
# 5. 失败路径：Agent 抛错（非 JSON）
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
        await run_archetype_rewrite_task(task_id, run_args)

    async with session_local() as db:
        task = await db.get(GenerationTask, task_id)
    assert task is not None
    assert task.status == GenerationTaskStatus.failed
    assert task.error


# ---------------------------------------------------------------------------
# 6. 结构保留 validator 失败
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_propagates_structure_validator_failure(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLM 把 4 镜砍成 3 镜 → ``validate_structure_preserved`` 抛 ValueError。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(db, variant_id="var-1")
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(
        monkeypatch,
        _MockChatModel(
            json.dumps(_make_structure_broken_script_dict(), ensure_ascii=False)
        ),
    )

    run_args = _base_run_args()
    task_id = await _create_task(session_local, run_args=run_args)
    with pytest.raises(ValueError, match="shot count changed"):
        await run_archetype_rewrite_task(task_id, run_args)

    async with session_local() as db:
        task = await db.get(GenerationTask, task_id)
        # 结构改变 → DB 上 variant.archetype 不应被刷新
        variant = await db.get(StoryVariant, "var-1")
    assert task is not None
    assert task.status == GenerationTaskStatus.failed
    assert variant is not None
    assert variant.archetype is None


# ---------------------------------------------------------------------------
# 7. 缺失 variant
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
    _patch_chat_openai(
        monkeypatch,
        _MockChatModel(json.dumps(_make_rewritten_script_dict(), ensure_ascii=False)),
    )

    run_args = _base_run_args(variant_id="not-exists")
    task_id = await _create_task(session_local, run_args=run_args)
    with pytest.raises(ValueError, match="StoryVariant not found"):
        await run_archetype_rewrite_task(task_id, run_args)

    async with session_local() as db:
        task = await db.get(GenerationTask, task_id)
    assert task is not None
    assert task.status == GenerationTaskStatus.failed


# ---------------------------------------------------------------------------
# 8. 空 script_breakdown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_raises_on_empty_script_breakdown(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """variant.script_breakdown 为空 → ValueError，不向 LLM 发请求。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(db, variant_id="var-1", script_breakdown={})
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(
        monkeypatch,
        _MockChatModel(json.dumps(_make_rewritten_script_dict(), ensure_ascii=False)),
    )

    run_args = _base_run_args()
    task_id = await _create_task(session_local, run_args=run_args)
    with pytest.raises(ValueError, match="script_breakdown"):
        await run_archetype_rewrite_task(task_id, run_args)


# ---------------------------------------------------------------------------
# 9. 注册表 / 配置常量
# ---------------------------------------------------------------------------


def test_executor_registered_with_correct_task_kind() -> None:
    """task_executor_registry 解析 ``archetype_rewrite`` → AbstractAsyncDelegatingExecutor。"""

    executor = task_executor_registry.resolve(TASK_KIND)
    assert isinstance(executor, AbstractAsyncDelegatingExecutor)
    assert executor.task_kind == TASK_KIND


def test_executor_timeout_set_to_600s() -> None:
    """注册时使用 ``DEFAULT_TIMEOUT_SEC`` (600s) 作为默认超时。"""

    executor = build_archetype_rewrite_executor()
    assert executor.timeout_seconds == DEFAULT_TIMEOUT_SEC == 600.0
    assert executor.task_kind == TASK_KIND


# ---------------------------------------------------------------------------
# 10. 透传：完整 vars 喂给 Agent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_passes_full_vars_to_agent(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_args 中的全部字段必须以 ``ArchetypeRewriteVars`` 形式透传给 Agent。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(db, variant_id="var-1")
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(
        monkeypatch,
        _MockChatModel(json.dumps(_make_rewritten_script_dict(), ensure_ascii=False)),
    )

    captured: dict[str, Any] = {}

    # pylint: disable=import-outside-toplevel
    from app.services.commerce import archetype_rewrite_worker as worker_mod

    real_a_rewrite_voice = (
        worker_mod.ArchetypeVoiceRewriterAgent.a_rewrite_voice  # type: ignore[attr-defined]
    )

    async def _spy_a_rewrite_voice(  # noqa: ANN001,A002
        self: Any,
        *,
        vars: Any,  # pylint: disable=redefined-builtin
    ):
        captured["vars"] = vars
        return await real_a_rewrite_voice(self, vars=vars)

    monkeypatch.setattr(
        (
            "app.services.commerce.archetype_rewrite_worker."
            "ArchetypeVoiceRewriterAgent.a_rewrite_voice"
        ),
        _spy_a_rewrite_voice,
    )

    run_args = _base_run_args(
        archetype="storyteller",
        archetype_description="说书人：娓娓道来",
        tone_grid={"formality": 4, "humanity": 8},
        words_to_avoid=["绝对", "保证"],
        preferred_vocab=["故事", "时光"],
    )
    task_id = await _create_task(session_local, run_args=run_args)
    await run_archetype_rewrite_task(task_id, run_args)

    captured_vars = captured.get("vars")
    assert captured_vars is not None
    assert captured_vars.archetype == "storyteller"
    assert captured_vars.archetype_description == "说书人：娓娓道来"
    assert captured_vars.tone_grid == {"formality": 4, "humanity": 8}
    assert captured_vars.words_to_avoid == ["绝对", "保证"]
    assert captured_vars.preferred_vocab == ["故事", "时光"]
    assert captured_vars.original_script["formula_id"] == "dramatic_reversal"


# ---------------------------------------------------------------------------
# 11. 任务状态推进
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
    _patch_chat_openai(
        monkeypatch,
        _MockChatModel(json.dumps(_make_rewritten_script_dict(), ensure_ascii=False)),
    )

    run_args = _base_run_args()
    task_id = await _create_task(session_local, run_args=run_args)
    await run_archetype_rewrite_task(task_id, run_args)

    async with session_local() as db:
        task = await db.get(GenerationTask, task_id)
    assert task is not None
    assert task.status == GenerationTaskStatus.succeeded
    assert task.progress == 100


# ---------------------------------------------------------------------------
# 12. tone_grid 防御性归一化
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_coerces_non_int_tone_grid_values(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """tone_grid 中数字串值应被转 int；非数字值静默丢弃，不应让任务失败。"""

    session_local = session_factory
    async with session_local() as db:
        await _seed_provider_and_model(db)
        await _seed_variant(db, variant_id="var-1")
        await db.commit()

    _patch_session_maker(monkeypatch, session_local)
    _patch_chat_openai(
        monkeypatch,
        _MockChatModel(json.dumps(_make_rewritten_script_dict(), ensure_ascii=False)),
    )

    captured: dict[str, Any] = {}

    # pylint: disable=import-outside-toplevel
    from app.services.commerce import archetype_rewrite_worker as worker_mod

    real_a_rewrite_voice = (
        worker_mod.ArchetypeVoiceRewriterAgent.a_rewrite_voice  # type: ignore[attr-defined]
    )

    async def _spy_a_rewrite_voice(  # noqa: ANN001,A002
        self: Any,
        *,
        vars: Any,  # pylint: disable=redefined-builtin
    ):
        captured["vars"] = vars
        return await real_a_rewrite_voice(self, vars=vars)

    monkeypatch.setattr(
        (
            "app.services.commerce.archetype_rewrite_worker."
            "ArchetypeVoiceRewriterAgent.a_rewrite_voice"
        ),
        _spy_a_rewrite_voice,
    )

    run_args = _base_run_args(
        tone_grid={"formality": "5", "humor": "not-a-number", "humanity": 7},
    )
    task_id = await _create_task(session_local, run_args=run_args)
    await run_archetype_rewrite_task(task_id, run_args)

    captured_vars = captured.get("vars")
    assert captured_vars is not None
    # "5" -> 5；"not-a-number" 被丢弃；7 保留
    assert captured_vars.tone_grid == {"formality": 5, "humanity": 7}
