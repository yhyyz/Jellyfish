"""``story_script_generate_worker`` 功能性测试（W5-T2）。

测试目标：

1. ``run_story_script_generate_task`` 在合法 ``run_args`` 下生成
   :class:`StoryVariant` 并完整持久化所有字段；
2. 必填字段（``project_id`` / ``chapter_id`` / ``formula_id``）缺失时立刻
   抛出 ``ValueError``，避免向 LLM 发出请求；
3. ``StoryGenerationVars`` 字段越界（如 ``target_duration_sec``）时
   ``pydantic.ValidationError`` 自然向上抛出；
4. agent 抛出时长漂移 ``ValueError`` 时 worker 不吞错；
5. ``compliance_score`` 维持 0（W5-T3 任务才会写入）；
6. ``task_executor_registry`` 正确解析 ``story_script_generate`` task_kind
   并将 ``timeout_seconds`` 设为 600s。

测试 DB 走 ``sqlite+aiosqlite:///:memory:`` 异步引擎，与项目其它 service
测试保持一致（参考 ``test_alembic_commerce_migrations.py`` 的全模型 import
模式建表，参考 ``test_compliance_rule_engine.py`` 的 ``_build_session``
helper 模式，避免与 pytest_asyncio strict 模式中 async fixture 冲突）。
Agent 用最小可用 stub 注入，避免命中真实 LLM。
"""

# pylint: disable=invalid-name,unnecessary-lambda

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.contracts.story import Shot, StoryGenerationVars, StoryScript
from app.core.db import Base

# 必须 import 全部模型，确保 Base.metadata 拥有完整 schema。
import app.models.api_quota  # noqa: F401  pylint: disable=unused-import
import app.models.commerce_assets  # noqa: F401  pylint: disable=unused-import
import app.models.compliance  # noqa: F401  pylint: disable=unused-import
import app.models.llm  # noqa: F401  pylint: disable=unused-import
import app.models.story_formula  # noqa: F401  pylint: disable=unused-import
import app.models.studio  # noqa: F401  pylint: disable=unused-import
import app.models.task  # noqa: F401  pylint: disable=unused-import
import app.models.task_links  # noqa: F401  pylint: disable=unused-import

from app.models.story_formula import StoryFormula, StoryVariant
from app.models.studio_projects import Chapter, Project
from app.models.studio_prompts_files_timeline import PromptTemplate
from app.models.types import (
    ChapterStatus,
    PromptCategory,
    ProjectStyle,
    ProjectVisualStyle,
    StoryVariantStatus,
)
from app.services.commerce.story_script_generate_worker import (
    DEFAULT_TIMEOUT_SEC,
    TASK_KIND,
    build_story_script_generate_executor,
    run_story_script_generate_task,
)
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_registry import task_executor_registry


# ---------------------------------------------------------------------------
# 测试辅助：脚本与 vars 工厂
# ---------------------------------------------------------------------------


def _make_shot(
    *,
    shot_id: str,
    duration_sec: float,
    product_focus_level: str = "none",
    is_brand_mention: bool = False,
) -> Shot:
    """构造合法 Shot；仅暴露关键差异，其它字段使用稳定占位值。"""
    return Shot(
        id=shot_id,
        duration_sec=duration_sec,
        function="generic",
        shot_type="medium",
        camera_angle="eye_level",
        camera_movement="static",
        dialog="测试对白",
        narration=None,
        product_focus_level=product_focus_level,  # type: ignore[arg-type]
        is_punchline=False,
        is_brand_mention=is_brand_mention,
        notes=None,
    )


def _make_script(target_duration_sec: int = 60) -> StoryScript:
    """构造满足 duration drift / brand cap 的 4 镜 ``target_duration_sec`` 脚本。"""
    per_shot = target_duration_sec / 4
    shots = [
        _make_shot(shot_id=f"shot_{i:03d}", duration_sec=per_shot)
        for i in range(1, 5)
    ]
    return StoryScript(
        total_duration_sec=target_duration_sec,
        total_shots=4,
        formula_id="dramatic_reversal",
        shots=shots,
        opening_hook="你试过这个吗",
        cta_text="点击购物车下单 · Vitamin C Serum",
        brand_mention_count=0,
    )


def _make_run_args(
    *,
    project_id: str = "proj-001",
    chapter_id: str = "chap-001",
    formula_id: str = "underdog_triumph",
    target_duration_sec: int = 60,
    archetype: str = "sage",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造合法 run_args；测试通过 ``extra`` 注入额外字段。"""
    args: dict[str, Any] = {
        "project_id": project_id,
        "chapter_id": chapter_id,
        "formula_id": formula_id,
        "formula": {"id": formula_id, "beats": ["hook", "reveal", "cta"]},
        "product": {
            "name": "Vitamin C Serum",
            "brand": "Acme",
            "category": "beauty",
        },
        "audience": {"persona": "office_worker", "pain": "dull_skin"},
        "archetype": archetype,
        "tone_grid": {"formality": 0.3, "energy": 0.7},
        "target_duration_sec": target_duration_sec,
        "platform": "douyin",
    }
    if extra:
        args.update(extra)
    return args


class _StubAgent:
    """最小可用 agent stub —— 异步返回 canned StoryScript。"""

    def __init__(self, model: Any, *, script: StoryScript | None = None) -> None:
        self.model = model
        self._script = script if script is not None else _make_script()
        self.calls: list[StoryGenerationVars] = []

    async def a_generate_script(  # pylint: disable=redefined-builtin
        self, *, vars: StoryGenerationVars  # noqa: A002
    ) -> StoryScript:
        self.calls.append(vars)
        return self._script


class _RaisingAgent:
    """模拟 agent 抛 ``ValueError``（如 duration drift）。"""

    def __init__(self, model: Any, *, error: Exception | None = None) -> None:
        self.model = model
        self._error = error or ValueError(
            "duration drift 25.0% exceeds tolerance 10%: target=60s actual=75.0s"
        )

    async def a_generate_script(  # pylint: disable=redefined-builtin
        self, *, vars: StoryGenerationVars  # noqa: A002
    ) -> StoryScript:
        raise self._error


# ---------------------------------------------------------------------------
# In-memory SQLite + FK 行 helper
# ---------------------------------------------------------------------------


async def _build_session_factory() -> tuple[
    Callable[[], AsyncSession], AsyncEngine
]:
    """构造一次性 SQLite ``:memory:`` 异步引擎并预置 FK 行。

    StoryVariant 的 FK：
    - ``project_id`` -> projects（须先插入一条 ``Project``）
    - ``chapter_id`` -> chapters（依赖 ``Project``）
    - ``formula_id`` -> story_formulas（依赖 ``PromptTemplate``）

    返回 ``(session_factory, engine)``：``session_factory`` 与生产
    ``async_session_maker`` 一致，``engine`` 由调用方在测试结束时
    ``await engine.dispose()`` 清理。
    """
    engine: AsyncEngine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", future=True
    )
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_local() as setup_db:
        setup_db.add(
            PromptTemplate(
                id="story_formula_generator_v1",
                category=PromptCategory.story_formula_generator,
                name="stub-template",
                preview="",
                content="stub content",
                variables=[],
                is_default=False,
                is_system=True,
            )
        )
        await setup_db.flush()
        setup_db.add(
            StoryFormula(
                id="underdog_triumph",
                name="凡人逆袭",
                structure={"beats": []},
                risk_flags=[],
                sample_dialog="占位剧本",
                typical_duration_sec=60,
                typical_shot_count=4,
                psychology="占位",
                use_cases=[],
                avoid_cases=[],
                prompt_template_id="story_formula_generator_v1",
                is_system=True,
                sort_order=0,
            )
        )
        await setup_db.flush()
        setup_db.add(
            Project(
                id="proj-001",
                name="测试项目",
                description="",
                style=ProjectStyle.real_people_city,
                visual_style=ProjectVisualStyle.live_action,
                seed=0,
            )
        )
        await setup_db.flush()
        setup_db.add(
            Chapter(
                id="chap-001",
                project_id="proj-001",
                index=1,
                title="第一章",
                summary="",
                raw_text="",
                condensed_text="",
                storyboard_count=0,
                status=ChapterStatus.draft,
            )
        )
        await setup_db.commit()

    return session_local, engine


def _stub_llm_factory(_sync_db: Any) -> Any:
    """run_sync 注入：返回任意占位对象代替真实 LLM。"""

    class _DummyLLM:  # pragma: no cover - 占位类，仅供 stub agent 接收
        pass

    return _DummyLLM()


async def _fetch_variants(
    session_factory: Callable[[], AsyncSession],
) -> list[StoryVariant]:
    """读取当前所有 ``StoryVariant`` 行，便于断言数量与字段。"""
    async with session_factory() as db:
        return list((await db.execute(select(StoryVariant))).scalars().all())


# ---------------------------------------------------------------------------
# 1. 持久化字段、返回 variant_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_persists_story_variant_with_correct_fields() -> None:
    """合法 run_args -> StoryVariant 行写入，所有关键字段正确。"""
    session_factory, engine = await _build_session_factory()
    try:
        canned = _make_script()
        output = await run_story_script_generate_task(
            "task-1",
            _make_run_args(),
            session_factory=session_factory,
            agent_factory=lambda model: _StubAgent(model, script=canned),
            llm_factory=_stub_llm_factory,
        )
        rows = await _fetch_variants(session_factory)
    finally:
        await engine.dispose()

    assert len(rows) == 1
    row = rows[0]
    assert row.id == output["variant_id"]
    assert row.project_id == "proj-001"
    assert row.chapter_id == "chap-001"
    assert row.formula_id == "underdog_triumph"
    assert row.archetype == "sage"
    assert row.is_champion is False


@pytest.mark.asyncio
async def test_runner_returns_variant_id_in_output() -> None:
    """runner 返回 dict 必须暴露 ``variant_id`` 与 ``script``。"""
    session_factory, engine = await _build_session_factory()
    try:
        output = await run_story_script_generate_task(
            "task-1",
            _make_run_args(),
            session_factory=session_factory,
            agent_factory=lambda model: _StubAgent(model),
            llm_factory=_stub_llm_factory,
        )
    finally:
        await engine.dispose()

    assert isinstance(output["variant_id"], str)
    assert output["variant_id"]
    assert isinstance(output["script"], dict)
    assert output["script"]["formula_id"] == "dramatic_reversal"


# ---------------------------------------------------------------------------
# 2. JSON 序列化字段
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_serializes_script_full_text_as_json() -> None:
    """``script_full_text`` 必须为 JSON 字符串，且能反序列化回字典。"""
    session_factory, engine = await _build_session_factory()
    try:
        canned = _make_script()
        output = await run_story_script_generate_task(
            "task-1",
            _make_run_args(),
            session_factory=session_factory,
            agent_factory=lambda model: _StubAgent(model, script=canned),
            llm_factory=_stub_llm_factory,
        )
        async with session_factory() as db:
            row = (await db.execute(
                select(StoryVariant).where(StoryVariant.id == output["variant_id"])
            )).scalar_one()
        full_text = row.script_full_text
        breakdown = row.script_breakdown
    finally:
        await engine.dispose()

    parsed = json.loads(full_text)
    assert parsed["total_shots"] == 4
    assert parsed["formula_id"] == "dramatic_reversal"
    assert breakdown["formula_id"] == "dramatic_reversal"


# ---------------------------------------------------------------------------
# 3. status / 必填字段缺失
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_sets_status_to_ready_on_success() -> None:
    """成功路径下 ``status == StoryVariantStatus.ready.value``。"""
    session_factory, engine = await _build_session_factory()
    try:
        output = await run_story_script_generate_task(
            "task-1",
            _make_run_args(),
            session_factory=session_factory,
            agent_factory=lambda model: _StubAgent(model),
            llm_factory=_stub_llm_factory,
        )
        async with session_factory() as db:
            row = (await db.execute(
                select(StoryVariant).where(StoryVariant.id == output["variant_id"])
            )).scalar_one()
        status = row.status
    finally:
        await engine.dispose()

    assert status == StoryVariantStatus.ready.value


@pytest.mark.asyncio
async def test_runner_raises_on_missing_project_id() -> None:
    """缺 ``project_id`` -> 立刻抛 ``ValueError``，无 DB 写入。"""
    session_factory, engine = await _build_session_factory()
    try:
        args = _make_run_args()
        args.pop("project_id")
        with pytest.raises(ValueError, match="project_id"):
            await run_story_script_generate_task(
                "task-1",
                args,
                session_factory=session_factory,
                agent_factory=lambda model: _StubAgent(model),
                llm_factory=_stub_llm_factory,
            )
        rows = await _fetch_variants(session_factory)
    finally:
        await engine.dispose()
    assert rows == []


@pytest.mark.asyncio
async def test_runner_raises_on_missing_chapter_id() -> None:
    """缺 ``chapter_id`` -> ``ValueError``。"""
    session_factory, engine = await _build_session_factory()
    try:
        args = _make_run_args()
        args.pop("chapter_id")
        with pytest.raises(ValueError, match="chapter_id"):
            await run_story_script_generate_task(
                "task-1",
                args,
                session_factory=session_factory,
                agent_factory=lambda model: _StubAgent(model),
                llm_factory=_stub_llm_factory,
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_runner_raises_on_missing_formula_id() -> None:
    """缺 ``formula_id`` -> ``ValueError``。"""
    session_factory, engine = await _build_session_factory()
    try:
        args = _make_run_args()
        args.pop("formula_id")
        with pytest.raises(ValueError, match="formula_id"):
            await run_story_script_generate_task(
                "task-1",
                args,
                session_factory=session_factory,
                agent_factory=lambda model: _StubAgent(model),
                llm_factory=_stub_llm_factory,
            )
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# 4. Pydantic 范围校验
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_validates_target_duration_sec_range() -> None:
    """``target_duration_sec`` 越界 -> ``ValidationError``（来自 Pydantic）。"""
    session_factory, engine = await _build_session_factory()
    try:
        args = _make_run_args(target_duration_sec=5)  # 下限 15
        with pytest.raises(ValidationError):
            await run_story_script_generate_task(
                "task-1",
                args,
                session_factory=session_factory,
                agent_factory=lambda model: _StubAgent(model),
                llm_factory=_stub_llm_factory,
            )
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# 5. agent 入参与异常传播
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_passes_full_vars_to_agent() -> None:
    """runner 必须把 ``StoryGenerationVars`` 实例完整传给 agent。"""
    session_factory, engine = await _build_session_factory()
    captured: dict[str, Any] = {}

    def factory(model: Any) -> _StubAgent:
        agent = _StubAgent(model)
        captured["agent"] = agent
        return agent

    try:
        await run_story_script_generate_task(
            "task-1",
            _make_run_args(target_duration_sec=90, archetype="hero"),
            session_factory=session_factory,
            agent_factory=factory,
            llm_factory=_stub_llm_factory,
        )
    finally:
        await engine.dispose()

    agent = captured["agent"]
    assert len(agent.calls) == 1
    call_vars = agent.calls[0]
    assert isinstance(call_vars, StoryGenerationVars)
    assert call_vars.target_duration_sec == 90
    assert call_vars.archetype == "hero"
    assert call_vars.platform == "douyin"


@pytest.mark.asyncio
async def test_runner_propagates_duration_drift_validation_error() -> None:
    """agent 抛 ``ValueError`` 时 worker 必须如实抛出，不吞错。"""
    session_factory, engine = await _build_session_factory()
    err = ValueError(
        "duration drift 25.0% exceeds tolerance 10%: target=60s actual=75.0s"
    )
    try:
        with pytest.raises(ValueError, match="duration drift"):
            await run_story_script_generate_task(
                "task-1",
                _make_run_args(),
                session_factory=session_factory,
                agent_factory=lambda model: _RaisingAgent(model, error=err),
                llm_factory=_stub_llm_factory,
            )
        rows = await _fetch_variants(session_factory)
    finally:
        await engine.dispose()
    assert rows == []


# ---------------------------------------------------------------------------
# 6. 注册表注册 & 超时
# ---------------------------------------------------------------------------


def test_executor_registered_with_correct_task_kind() -> None:
    """``task_executor_registry.resolve("story_script_generate")`` 返回执行器。"""
    executor = task_executor_registry.resolve(TASK_KIND)
    assert executor.task_kind == TASK_KIND
    assert isinstance(executor, AbstractAsyncDelegatingExecutor)


def test_executor_timeout_set_to_600s() -> None:
    """``timeout_seconds`` 必须是 plan 约定的 600.0s。"""
    executor = build_story_script_generate_executor()
    assert executor.timeout_seconds == DEFAULT_TIMEOUT_SEC == 600.0


# ---------------------------------------------------------------------------
# 7. 合规分留 0 / variant id 是 uuid
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_does_not_compute_compliance_score() -> None:
    """``compliance_score`` 必须保持 0；合规检查由 W5-T3 单独 task_kind 写。"""
    session_factory, engine = await _build_session_factory()
    try:
        output = await run_story_script_generate_task(
            "task-1",
            _make_run_args(),
            session_factory=session_factory,
            agent_factory=lambda model: _StubAgent(model),
            llm_factory=_stub_llm_factory,
        )
        async with session_factory() as db:
            row = (await db.execute(
                select(StoryVariant).where(StoryVariant.id == output["variant_id"])
            )).scalar_one()
        score = row.compliance_score
    finally:
        await engine.dispose()
    assert score == 0


@pytest.mark.asyncio
async def test_runner_uses_uuid_for_variant_id() -> None:
    """两次运行得到的 ``variant_id`` 必须是非空且互不相同的字符串。"""
    session_factory, engine = await _build_session_factory()
    try:
        out1 = await run_story_script_generate_task(
            "task-1",
            _make_run_args(),
            session_factory=session_factory,
            agent_factory=lambda model: _StubAgent(model),
            llm_factory=_stub_llm_factory,
        )
        out2 = await run_story_script_generate_task(
            "task-2",
            _make_run_args(),
            session_factory=session_factory,
            agent_factory=lambda model: _StubAgent(model),
            llm_factory=_stub_llm_factory,
        )
    finally:
        await engine.dispose()

    vid1 = out1["variant_id"]
    vid2 = out2["variant_id"]
    assert vid1 and vid2
    assert vid1 != vid2
    # uuid4().hex 是 32 个十六进制字符。
    assert len(vid1) == 32
    assert all(c in "0123456789abcdef" for c in vid1)


# ---------------------------------------------------------------------------
# 8. generated_by_task_id 透传
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_persists_generated_by_task_id_when_provided() -> None:
    """``generated_by_task_id`` 透传至 StoryVariant 行（用于任务->变体反查）。"""
    session_factory, engine = await _build_session_factory()
    try:
        output = await run_story_script_generate_task(
            "task-original",
            _make_run_args(extra={"generated_by_task_id": "task-original"}),
            session_factory=session_factory,
            agent_factory=lambda model: _StubAgent(model),
            llm_factory=_stub_llm_factory,
        )
        async with session_factory() as db:
            row = (await db.execute(
                select(StoryVariant).where(StoryVariant.id == output["variant_id"])
            )).scalar_one()
        generated_by = row.generated_by_task_id
    finally:
        await engine.dispose()
    assert generated_by == "task-original"
