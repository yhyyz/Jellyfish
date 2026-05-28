"""``hook_writer_worker`` 任务执行器测试（W12 P2 TDD backfill）。

覆盖：

1. lifecycle：mock agent 驱动 ``run_hook_writer_task`` →
   task status running → succeeded、progress 100；
2. payload mutation：``StoryVariant.script_breakdown["opening_hook"]``
   被原地 patch 为 LLM 返回的 ``hook_text``；
3. cancel honored：取消标志触发后 worker 早退、不再写 succeeded；
4. agent failure：agent 抛错 → task 状态被独立 session 标记 ``failed``，
   ``error`` 字段含原始异常文本；
5. enqueue dispatch：
   - ``task_executor_registry.resolve("hook_writer")`` 返回正确执行器；
   - ``CommerceTaskDispatchService.enqueue_hook_writer`` 链路存在。
"""

# pylint: disable=protected-access,too-few-public-methods,redefined-outer-name

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 必须 import 全部模型以确保 Base.metadata 拥有完整 schema。
import app.models.api_quota  # noqa: F401  pylint: disable=unused-import
import app.models.commerce_assets  # noqa: F401  pylint: disable=unused-import
import app.models.compliance  # noqa: F401  pylint: disable=unused-import
import app.models.llm  # noqa: F401  pylint: disable=unused-import
import app.models.story_formula  # noqa: F401  pylint: disable=unused-import
import app.models.studio  # noqa: F401  pylint: disable=unused-import
import app.models.task  # noqa: F401  pylint: disable=unused-import
import app.models.task_links  # noqa: F401  pylint: disable=unused-import

from app.core.contracts.story import ShotHook
from app.core.db import Base
from app.core.task_manager import SqlAlchemyTaskStore
from app.core.task_manager.types import DeliveryMode
from app.models.story_formula import StoryFormula, StoryVariant
from app.models.studio_projects import Chapter, Project
from app.models.studio_prompts_files_timeline import PromptTemplate
from app.models.task import GenerationTask, GenerationTaskStatus
from app.models.types import (
    ChapterStatus,
    ProjectStyle,
    ProjectVisualStyle,
    PromptCategory,
    StoryVariantStatus,
)
from app.services.commerce.hook_writer_worker import (
    DEFAULT_TIMEOUT_SEC,
    TASK_KIND,
    run_hook_writer_task,
)
from app.services.commerce.task_dispatch import (
    CommerceTaskDispatchService,
    TASK_KIND_HOOK_WRITER,
)
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_registry import task_executor_registry


# ---------------------------------------------------------------------------
# Fixtures：file-backed SQLite + 全 FK 行
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    """构造 file-backed SQLite 引擎并预置 FK 行。

    使用 file-backed（而非 ``:memory:``）确保 worker 内部多次开
    ``async_session_maker()`` 会看到同一份数据库——这与 W5-T3 compliance
    worker 测试一致。
    """

    db_path = tmp_path / "hook-writer-worker.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_local = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_local() as setup_db:
        setup_db.add(
            PromptTemplate(
                id="tpl-hook-1",
                category=PromptCategory.hook_pattern_writer,
                name="占位模板",
                preview="",
                content="占位",
                variables=[],
                is_default=True,
                is_system=True,
            )
        )
        await setup_db.flush()
        setup_db.add(
            StoryFormula(
                id="formula-1",
                name="测试公式",
                structure={"beats": []},
                risk_flags=[],
                sample_dialog="占位剧本",
                typical_duration_sec=60,
                typical_shot_count=4,
                psychology="占位",
                use_cases=[],
                avoid_cases=[],
                prompt_template_id="tpl-hook-1",
                is_system=True,
                sort_order=0,
            )
        )
        await setup_db.flush()
        setup_db.add(
            Project(
                id="proj-1",
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
                id="chap-1",
                project_id="proj-1",
                index=1,
                title="第 1 章",
                summary="",
                raw_text="",
                condensed_text="",
                storyboard_count=0,
                status=ChapterStatus.draft,
            )
        )
        await setup_db.flush()
        setup_db.add(
            StoryVariant(
                id="var-1",
                project_id="proj-1",
                chapter_id="chap-1",
                formula_id="formula-1",
                script_full_text="占位脚本",
                script_breakdown={
                    "total_shots": 3,
                    "opening_hook": "原始钩子",
                    "cta_text": "原始 CTA",
                },
                status=StoryVariantStatus.draft.value,
            )
        )
        await setup_db.commit()

    yield session_local
    await engine.dispose()


# ---------------------------------------------------------------------------
# 共用 stub agent + helpers
# ---------------------------------------------------------------------------


class _StubAgent:
    """canned ShotHook 的最小 agent stub，用于替换真正的 ``HookWriterAgent``。"""

    def __init__(self, model: Any, *, hook: ShotHook | None = None) -> None:
        self.model = model
        self._hook = hook or ShotHook(
            hook_text="改写后的 3 秒钩子",
            pattern_id="p_curiosity_001",
            pattern_type="curiosity",
            rationale="curiosity-driven",
        )
        self.calls: list[dict[str, Any]] = []

    async def a_write_hook(  # pylint: disable=redefined-builtin
        self, *, vars  # noqa: A002
    ) -> ShotHook:
        self.calls.append({"vars": vars})
        return self._hook


class _RaisingAgent:
    """模拟 agent 抛错（如 ValidationError / 网络错）。"""

    def __init__(self, model: Any) -> None:
        self.model = model

    async def a_write_hook(  # pylint: disable=redefined-builtin
        self, *, vars  # noqa: A002
    ) -> ShotHook:
        raise RuntimeError("upstream LLM exploded")


def _patch_session_maker(monkeypatch, session_local) -> None:
    monkeypatch.setattr(
        "app.services.commerce.hook_writer_worker.async_session_maker",
        session_local,
    )


def _patch_llm(monkeypatch) -> None:
    """避免 worker 真去查 Provider/Model：直接返回占位 LLM。"""

    monkeypatch.setattr(
        "app.services.commerce.hook_writer_worker.build_default_text_llm_sync",
        lambda *_args, **_kwargs: MagicMock(name="LLM-stub"),
    )


def _patch_agent_class(monkeypatch, agent_cls) -> None:
    monkeypatch.setattr(
        "app.services.commerce.hook_writer_worker.HookWriterAgent",
        agent_cls,
    )


def _run_args() -> dict[str, Any]:
    return {
        "variant_id": "var-1",
        "pattern_id": "p_curiosity_001",
        "pattern_type": "curiosity",
        "product_name": "代餐奶昔",
        "product_description": "低卡饱腹",
        "audience_pain_points": ["减肥屡败"],
        "audience_demographics": {"age": "25-35"},
    }


async def _create_task(session_local, run_args: dict[str, Any]) -> str:
    async with session_local() as db:
        store = SqlAlchemyTaskStore(db)
        task = await store.create(
            payload={"task_kind": TASK_KIND, "run_args": run_args},
            mode=DeliveryMode.async_polling,
            task_kind=TASK_KIND,
        )
        await db.commit()
        return task.id


# ---------------------------------------------------------------------------
# 1. lifecycle: running -> succeeded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_lifecycle_succeeds_with_progress_100(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """合法 run_args + stub agent → task succeeded、progress=100、result 落库。"""

    _patch_session_maker(monkeypatch, session_factory)
    _patch_llm(monkeypatch)
    _patch_agent_class(monkeypatch, _StubAgent)

    task_id = await _create_task(session_factory, _run_args())

    await run_hook_writer_task(task_id, _run_args())

    async with session_factory() as db:
        task = await db.get(GenerationTask, task_id)

    assert task is not None
    assert task.status == GenerationTaskStatus.succeeded
    assert task.progress == 100
    assert task.result is not None
    assert task.result["variant_id"] == "var-1"
    assert task.result["hook_text"] == "改写后的 3 秒钩子"
    assert task.result["pattern_type"] == "curiosity"


# ---------------------------------------------------------------------------
# 2. payload mutation: StoryVariant.script_breakdown["opening_hook"] 被改写
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_patches_variant_opening_hook_in_place(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """worker 成功后，``script_breakdown.opening_hook`` 被改为新的钩子文本。"""

    _patch_session_maker(monkeypatch, session_factory)
    _patch_llm(monkeypatch)
    _patch_agent_class(monkeypatch, _StubAgent)

    task_id = await _create_task(session_factory, _run_args())

    await run_hook_writer_task(task_id, _run_args())

    async with session_factory() as db:
        variant = await db.get(StoryVariant, "var-1")

    assert variant is not None
    assert variant.script_breakdown["opening_hook"] == "改写后的 3 秒钩子"
    # 其它字段保持原值，证明是 in-place patch 而非整段覆盖。
    assert variant.script_breakdown["cta_text"] == "原始 CTA"
    assert variant.script_breakdown["total_shots"] == 3


# ---------------------------------------------------------------------------
# 3. cancel honored: pre-execute cancel 让 worker 早退
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_honors_pre_execute_cancellation(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """task 被预先标记 cancel_requested → worker 早退、不写 succeeded、不改 variant。"""

    _patch_session_maker(monkeypatch, session_factory)
    _patch_llm(monkeypatch)
    _patch_agent_class(monkeypatch, _StubAgent)

    task_id = await _create_task(session_factory, _run_args())

    # 预先把 cancel_requested 置为 True（worker 第一次检查就会命中）。
    async with session_factory() as db:
        store = SqlAlchemyTaskStore(db)
        await store.request_cancel(task_id)
        await db.commit()

    await run_hook_writer_task(task_id, _run_args())

    async with session_factory() as db:
        task = await db.get(GenerationTask, task_id)
        variant = await db.get(StoryVariant, "var-1")

    assert task is not None
    # 取消语义：worker 不应进入 succeeded；status 通常变为 cancelled。
    assert task.status != GenerationTaskStatus.succeeded
    # variant.opening_hook 没被改写。
    assert variant is not None
    assert variant.script_breakdown["opening_hook"] == "原始钩子"


# ---------------------------------------------------------------------------
# 4. agent failure: 上游异常 → task failed + error 文本可见
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_marks_failed_when_agent_raises(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """agent 抛 RuntimeError → task 状态 failed、error 字段保留原异常消息。"""

    _patch_session_maker(monkeypatch, session_factory)
    _patch_llm(monkeypatch)
    _patch_agent_class(monkeypatch, _RaisingAgent)

    task_id = await _create_task(session_factory, _run_args())

    with pytest.raises(RuntimeError):
        await run_hook_writer_task(task_id, _run_args())

    async with session_factory() as db:
        task = await db.get(GenerationTask, task_id)
        variant = await db.get(StoryVariant, "var-1")

    assert task is not None
    assert task.status == GenerationTaskStatus.failed
    assert "upstream LLM exploded" in (task.error or "")
    # variant 未被改写，证明事务回滚生效。
    assert variant is not None
    assert variant.script_breakdown["opening_hook"] == "原始钩子"


# ---------------------------------------------------------------------------
# 5. enqueue dispatch: registry + task_dispatch.enqueue_hook_writer
# ---------------------------------------------------------------------------


def test_executor_registered_with_correct_task_kind_and_timeout() -> None:
    """``task_executor_registry`` 解析 ``hook_writer`` → 正确执行器与超时。"""

    executor = task_executor_registry.resolve(TASK_KIND)
    assert isinstance(executor, AbstractAsyncDelegatingExecutor)
    assert executor.task_kind == TASK_KIND == "hook_writer"
    assert executor.timeout_seconds == DEFAULT_TIMEOUT_SEC == 180.0


@pytest.mark.asyncio
async def test_dispatch_service_enqueue_hook_writer_persists_task_row(
    session_factory,
) -> None:
    """``CommerceTaskDispatchService.enqueue_hook_writer`` 存在且能落表。

    存在性是 P2 W12 链路要求；此处不测 broker 投递（W19b 拆段：commit 后
    才 dispatch），只断言：
      - 方法可调用；
      - 返回 descriptor.task_kind 与常量对齐；
      - DB 落了对应 ``GenerationTask`` 行。
    """

    assert hasattr(CommerceTaskDispatchService, "enqueue_hook_writer")
    assert TASK_KIND_HOOK_WRITER == "hook_writer"

    async with session_factory() as db:
        service = CommerceTaskDispatchService(db)
        descriptor = await service.enqueue_hook_writer(_run_args())
        await db.commit()

    assert descriptor.task_kind == TASK_KIND_HOOK_WRITER
    assert descriptor.queue == "fast"
    async with session_factory() as db:
        row = await db.get(GenerationTask, descriptor.task_id)
    assert row is not None
    assert row.task_kind == "hook_writer"
    assert row.payload["task_kind"] == "hook_writer"
    assert row.payload["run_args"]["variant_id"] == "var-1"
