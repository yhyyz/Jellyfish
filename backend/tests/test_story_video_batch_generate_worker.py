"""W14-T1: ``story_video_batch_generate`` 任务执行器测试。

测试目标
========

1. **注册元数据**：``task_executor_registry`` 能解析到执行器，且
   ``timeout_seconds==7200``、``DEFAULT_QUEUE=="slow"``；
2. **入参校验**：必填字段、变体长度、时长范围、并发上限的 Pydantic
   边界条件全部走 ``ValidationError``；
3. **入队语义**：N 个 variants -> N 个子 ``GenerationTask`` 行落盘 +
   N 次 ``send_task`` 投递；
4. **结果返回**：``runner`` 返回 ``{batch_id, child_task_ids,
   variant_count, status}``；
5. **父子关联**：每个子任务 ``payload['parent_batch_id']`` 都指向
   当前批量任务自身的 ``task_id``。

测试 DB 走 ``sqlite+aiosqlite:///:memory:`` 异步引擎，与
``test_story_script_generate_worker.py`` 风格一致；Celery 投递通过
``send_task`` 注入 ``MagicMock`` 拦截，避免连真 broker。
"""

# pylint: disable=invalid-name,too-many-arguments

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

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

from app.models.task import GenerationTask, GenerationTaskStatus
from app.services.commerce.story_video_batch_generate_worker import (
    CHILD_QUEUE,
    CHILD_TASK_KIND,
    DEFAULT_QUEUE,
    DEFAULT_TIMEOUT_SEC,
    TASK_KIND,
    build_story_video_batch_generate_executor,
    run_story_video_batch_generate_task,
)
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_registry import task_executor_registry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_variant_spec(
    *,
    formula_id: str = "underdog_triumph",
    archetype: str | None = "sage",
    hook_pattern_id: str | None = None,
    cta_pattern_id: str | None = None,
    tone_grid: dict[str, int] | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """构造合法的 variant spec dict（非 BatchVariantSpec 实例，以便测 422）。"""

    spec: dict[str, Any] = {"formula_id": formula_id}
    if archetype is not None:
        spec["archetype"] = archetype
    if hook_pattern_id is not None:
        spec["hook_pattern_id"] = hook_pattern_id
    if cta_pattern_id is not None:
        spec["cta_pattern_id"] = cta_pattern_id
    if tone_grid is not None:
        spec["tone_grid"] = dict(tone_grid)
    if label is not None:
        spec["label"] = label
    return spec


def _make_run_args(
    *,
    project_id: str = "proj-001",
    chapter_id: str = "chap-001",
    target_duration_sec: int = 60,
    platform: str = "douyin",
    parallelism: int = 2,
    variants: list[dict[str, Any]] | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造合法的 run_args；测试通过 ``overrides`` 注入越界字段。"""

    if variants is None:
        variants = [_make_variant_spec()]
    args: dict[str, Any] = {
        "project_id": project_id,
        "chapter_id": chapter_id,
        "product": {"name": "Vitamin C Serum", "category": "beauty"},
        "audience": {"persona": "office_worker"},
        "target_duration_sec": target_duration_sec,
        "platform": platform,
        "variants": variants,
        "parallelism": parallelism,
    }
    if overrides:
        args.update(overrides)
    return args


async def _build_session_factory() -> tuple[
    Callable[[], AsyncSession], AsyncEngine
]:
    """构造一次性 SQLite ``:memory:`` 异步引擎，并预置一行 batch task。

    与 ``test_story_script_generate_worker.py._build_session_factory`` 不同，
    本测试不需要 ``StoryFormula`` / ``Project`` / ``Chapter`` 的 FK 行：
    ``story_video_batch_generate`` worker 只写 :class:`GenerationTask`，
    不写 :class:`StoryVariant`。
    """

    engine: AsyncEngine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", future=True
    )
    session_local = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    return session_local, engine


async def _seed_batch_task(
    session_factory: Callable[[], AsyncSession],
    *,
    task_id: str,
    run_args: dict[str, Any],
) -> None:
    """在测试 DB 中预置一行 batch ``GenerationTask`` 让 store 能更新。"""

    async with session_factory() as db:
        db.add(
            GenerationTask(
                id=task_id,
                mode="async_polling",
                task_kind=TASK_KIND,
                status=GenerationTaskStatus.pending,
                progress=0,
                payload={"task_kind": TASK_KIND, "run_args": run_args},
                result=None,
                error="",
            )
        )
        await db.commit()


async def _fetch_child_rows(
    session_factory: Callable[[], AsyncSession],
) -> list[GenerationTask]:
    """读取所有 ``story_script_generate`` 子任务行。"""

    async with session_factory() as db:
        rows = (
            await db.execute(
                select(GenerationTask).where(
                    GenerationTask.task_kind == CHILD_TASK_KIND
                )
            )
        ).scalars().all()
        return list(rows)


# ---------------------------------------------------------------------------
# Registry & timeout & queue
# ---------------------------------------------------------------------------


def test_executor_registered_with_correct_task_kind() -> None:
    """``task_executor_registry`` 必须能解析到 batch worker。"""

    executor = task_executor_registry.resolve(TASK_KIND)
    assert executor.task_kind == TASK_KIND
    assert isinstance(executor, AbstractAsyncDelegatingExecutor)


def test_executor_timeout_set_to_7200s() -> None:
    """plan W14 D 节定的 batch 超时硬约束 = 7200 秒。"""

    executor = build_story_video_batch_generate_executor()
    assert executor.timeout_seconds == DEFAULT_TIMEOUT_SEC == 7200.0


def test_executor_uses_slow_queue() -> None:
    """worker 模块必须显式声明 ``DEFAULT_QUEUE == 'slow'``，让调度服务复用。"""

    assert DEFAULT_QUEUE == "slow"


# ---------------------------------------------------------------------------
# Pydantic 校验：必填 / 边界
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_validates_required_project_id() -> None:
    """缺 ``project_id`` -> ``ValidationError``，无任何 DB 写入。"""

    session_factory, engine = await _build_session_factory()
    await _seed_batch_task(
        session_factory, task_id="batch-1", run_args={"placeholder": True}
    )
    args = _make_run_args()
    args.pop("project_id")
    try:
        with pytest.raises(ValidationError):
            await run_story_video_batch_generate_task(
                "batch-1",
                args,
                session_factory=session_factory,
                send_task=MagicMock(),
            )
        rows = await _fetch_child_rows(session_factory)
    finally:
        await engine.dispose()
    assert rows == []


@pytest.mark.asyncio
async def test_runner_validates_min_1_variant() -> None:
    """``variants`` 长度 0 -> ``ValidationError``。"""

    session_factory, engine = await _build_session_factory()
    await _seed_batch_task(session_factory, task_id="batch-1", run_args={})
    args = _make_run_args(variants=[])
    try:
        with pytest.raises(ValidationError):
            await run_story_video_batch_generate_task(
                "batch-1",
                args,
                session_factory=session_factory,
                send_task=MagicMock(),
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_runner_validates_max_10_variants() -> None:
    """``variants`` 长度 11 -> ``ValidationError``，避免一次性把队列撑爆。"""

    session_factory, engine = await _build_session_factory()
    await _seed_batch_task(session_factory, task_id="batch-1", run_args={})
    variants = [_make_variant_spec(label=f"v-{i}") for i in range(11)]
    args = _make_run_args(variants=variants)
    try:
        with pytest.raises(ValidationError):
            await run_story_video_batch_generate_task(
                "batch-1",
                args,
                session_factory=session_factory,
                send_task=MagicMock(),
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_runner_validates_target_duration_range() -> None:
    """``target_duration_sec`` 越界（<15 或 >180） -> ``ValidationError``。"""

    session_factory, engine = await _build_session_factory()
    await _seed_batch_task(session_factory, task_id="batch-1", run_args={})
    try:
        with pytest.raises(ValidationError):
            await run_story_video_batch_generate_task(
                "batch-1",
                _make_run_args(target_duration_sec=10),
                session_factory=session_factory,
                send_task=MagicMock(),
            )
        with pytest.raises(ValidationError):
            await run_story_video_batch_generate_task(
                "batch-1",
                _make_run_args(target_duration_sec=181),
                session_factory=session_factory,
                send_task=MagicMock(),
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_runner_validates_parallelism_range() -> None:
    """``parallelism`` 越界（<1 或 >4） -> ``ValidationError``。"""

    session_factory, engine = await _build_session_factory()
    await _seed_batch_task(session_factory, task_id="batch-1", run_args={})
    try:
        with pytest.raises(ValidationError):
            await run_story_video_batch_generate_task(
                "batch-1",
                _make_run_args(parallelism=0),
                session_factory=session_factory,
                send_task=MagicMock(),
            )
        with pytest.raises(ValidationError):
            await run_story_video_batch_generate_task(
                "batch-1",
                _make_run_args(parallelism=5),
                session_factory=session_factory,
                send_task=MagicMock(),
            )
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# 入队语义 / 结果 / 父子关联
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_enqueues_n_child_tasks() -> None:
    """N 个 variants -> N 次 ``send_task`` 调用，且队列固定为 ``fast``。"""

    session_factory, engine = await _build_session_factory()
    await _seed_batch_task(session_factory, task_id="batch-1", run_args={})
    variants = [
        _make_variant_spec(formula_id="f1", label="v1"),
        _make_variant_spec(formula_id="f2", label="v2"),
        _make_variant_spec(formula_id="f3", label="v3"),
    ]
    fake_send = MagicMock()
    try:
        await run_story_video_batch_generate_task(
            "batch-1",
            _make_run_args(variants=variants),
            session_factory=session_factory,
            send_task=fake_send,
        )
    finally:
        await engine.dispose()

    assert fake_send.call_count == 3
    for call in fake_send.call_args_list:
        args, kwargs = call
        assert args[0] == "task.execute"
        assert kwargs["queue"] == CHILD_QUEUE == "fast"
        assert isinstance(kwargs["args"], list) and len(kwargs["args"]) == 1


@pytest.mark.asyncio
async def test_runner_returns_child_task_ids_in_result() -> None:
    """runner 返回 dict 必须暴露 ``child_task_ids`` / ``variant_count`` / ``status``。"""

    session_factory, engine = await _build_session_factory()
    await _seed_batch_task(session_factory, task_id="batch-1", run_args={})
    variants = [
        _make_variant_spec(formula_id="f1"),
        _make_variant_spec(formula_id="f2"),
    ]
    fake_send = MagicMock()
    try:
        result = await run_story_video_batch_generate_task(
            "batch-1",
            _make_run_args(variants=variants),
            session_factory=session_factory,
            send_task=fake_send,
        )
    finally:
        await engine.dispose()

    assert result["batch_id"] == "batch-1"
    assert result["status"] == "enqueued"
    assert result["variant_count"] == 2
    assert isinstance(result["child_task_ids"], list)
    assert len(result["child_task_ids"]) == 2
    assert all(isinstance(tid, str) and len(tid) == 32 for tid in result["child_task_ids"])
    assert result["child_task_ids"][0] != result["child_task_ids"][1]


@pytest.mark.asyncio
async def test_runner_persists_child_task_rows_in_db() -> None:
    """每个 variant 必须落一行 ``story_script_generate`` 子任务 + 状态 pending。"""

    session_factory, engine = await _build_session_factory()
    await _seed_batch_task(session_factory, task_id="batch-1", run_args={})
    variants = [
        _make_variant_spec(formula_id="f1", archetype="sage"),
        _make_variant_spec(formula_id="f2", archetype="hero"),
    ]
    try:
        await run_story_video_batch_generate_task(
            "batch-1",
            _make_run_args(variants=variants),
            session_factory=session_factory,
            send_task=MagicMock(),
        )
        rows = await _fetch_child_rows(session_factory)
    finally:
        await engine.dispose()

    assert len(rows) == 2
    formula_ids = {row.payload["run_args"]["formula_id"] for row in rows}
    assert formula_ids == {"f1", "f2"}
    for row in rows:
        assert row.task_kind == CHILD_TASK_KIND
        assert row.status == GenerationTaskStatus.pending
        assert row.payload["task_kind"] == CHILD_TASK_KIND
        run_args = row.payload["run_args"]
        assert run_args["project_id"] == "proj-001"
        assert run_args["chapter_id"] == "chap-001"
        assert run_args["platform"] == "douyin"
        assert run_args["target_duration_sec"] == 60


@pytest.mark.asyncio
async def test_runner_passes_parent_batch_id_to_children() -> None:
    """每个子任务的 ``payload['parent_batch_id']`` 必须等于父 ``task_id``。"""

    session_factory, engine = await _build_session_factory()
    await _seed_batch_task(session_factory, task_id="batch-xyz", run_args={})
    variants = [
        _make_variant_spec(formula_id="f1"),
        _make_variant_spec(formula_id="f2"),
        _make_variant_spec(formula_id="f3"),
    ]
    try:
        await run_story_video_batch_generate_task(
            "batch-xyz",
            _make_run_args(variants=variants),
            session_factory=session_factory,
            send_task=MagicMock(),
        )
        rows = await _fetch_child_rows(session_factory)
    finally:
        await engine.dispose()

    assert len(rows) == 3
    for row in rows:
        assert row.payload["parent_batch_id"] == "batch-xyz"
