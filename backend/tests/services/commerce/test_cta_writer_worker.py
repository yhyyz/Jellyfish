"""``cta_writer_worker`` 任务执行器测试（W12 P2 TDD backfill）。

覆盖：

1. lifecycle：mock agent → task running → succeeded、progress=100；
2. payload mutation：``StoryVariant.script_breakdown["cta_text"]`` 被原地改写；
3. cancel honored：pre-execute cancel 让 worker 早退；
4. agent failure：agent 抛错 → task 失败、error 字段含原异常文本；
5. enqueue dispatch：registry 注册 + ``enqueue_cta_writer`` 链路存在。
"""

# pylint: disable=protected-access,too-few-public-methods,redefined-outer-name

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models.api_quota  # noqa: F401  pylint: disable=unused-import
import app.models.commerce_assets  # noqa: F401  pylint: disable=unused-import
import app.models.compliance  # noqa: F401  pylint: disable=unused-import
import app.models.llm  # noqa: F401  pylint: disable=unused-import
import app.models.story_formula  # noqa: F401  pylint: disable=unused-import
import app.models.studio  # noqa: F401  pylint: disable=unused-import
import app.models.task  # noqa: F401  pylint: disable=unused-import
import app.models.task_links  # noqa: F401  pylint: disable=unused-import

from app.core.contracts.story import CTAText
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
from app.services.commerce.cta_writer_worker import (
    DEFAULT_TIMEOUT_SEC,
    TASK_KIND,
    run_cta_writer_task,
)
from app.services.commerce.task_dispatch import (
    CommerceTaskDispatchService,
    TASK_KIND_CTA_WRITER,
)
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_registry import task_executor_registry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    db_path = tmp_path / "cta-writer-worker.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_local = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_local() as setup_db:
        setup_db.add(
            PromptTemplate(
                id="tpl-cta-1",
                category=PromptCategory.cta_pattern_writer,
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
                prompt_template_id="tpl-cta-1",
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
                id="var-cta",
                project_id="proj-1",
                chapter_id="chap-1",
                formula_id="formula-1",
                script_full_text="占位脚本",
                script_breakdown={
                    "total_shots": 3,
                    "opening_hook": "原始钩子",
                    "cta_text": "原始 CTA 文案",
                },
                status=StoryVariantStatus.draft.value,
            )
        )
        await setup_db.commit()

    yield session_local
    await engine.dispose()


# ---------------------------------------------------------------------------
# Stub agents
# ---------------------------------------------------------------------------


class _StubAgent:
    """canned CTAText 的最小 agent stub。"""

    def __init__(self, model: Any, *, cta: CTAText | None = None) -> None:
        self.model = model
        self._cta = cta or CTAText(
            cta_text="今天下单立省 50，限量 100 份！",
            pattern_id="p_scarcity_001",
            hardness="medium",
            urgency_type="scarcity",
            rationale="稀缺驱动",
        )
        self.calls: list[dict[str, Any]] = []

    async def a_write_cta(  # pylint: disable=redefined-builtin
        self, *, vars  # noqa: A002
    ) -> CTAText:
        self.calls.append({"vars": vars})
        return self._cta


class _RaisingAgent:
    def __init__(self, model: Any) -> None:
        self.model = model

    async def a_write_cta(  # pylint: disable=redefined-builtin
        self, *, vars  # noqa: A002
    ) -> CTAText:
        raise RuntimeError("CTA generation timed out")


def _patch_session_maker(monkeypatch, session_local) -> None:
    monkeypatch.setattr(
        "app.services.commerce.cta_writer_worker.async_session_maker",
        session_local,
    )


def _patch_llm(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.commerce.cta_writer_worker.build_default_text_llm_sync",
        lambda *_args, **_kwargs: MagicMock(name="LLM-stub"),
    )


def _patch_agent_class(monkeypatch, agent_cls) -> None:
    monkeypatch.setattr(
        "app.services.commerce.cta_writer_worker.CTAWriterAgent",
        agent_cls,
    )


def _run_args() -> dict[str, Any]:
    return {
        "variant_id": "var-cta",
        "pattern_id": "p_scarcity_001",
        "hardness": "medium",
        "urgency_type": "scarcity",
        "product_name": "代餐奶昔",
        "product_url": "https://example.com/p/123",
        "discount_text": "立减 50",
        "target_action": "加购",
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
# 1. lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_lifecycle_succeeds_with_progress_100(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_session_maker(monkeypatch, session_factory)
    _patch_llm(monkeypatch)
    _patch_agent_class(monkeypatch, _StubAgent)

    task_id = await _create_task(session_factory, _run_args())

    await run_cta_writer_task(task_id, _run_args())

    async with session_factory() as db:
        task = await db.get(GenerationTask, task_id)

    assert task is not None
    assert task.status == GenerationTaskStatus.succeeded
    assert task.progress == 100
    assert task.result is not None
    assert task.result["variant_id"] == "var-cta"
    assert task.result["cta_text"] == "今天下单立省 50，限量 100 份！"
    assert task.result["hardness"] == "medium"
    assert task.result["urgency_type"] == "scarcity"


# ---------------------------------------------------------------------------
# 2. payload mutation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_patches_variant_cta_text_in_place(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_session_maker(monkeypatch, session_factory)
    _patch_llm(monkeypatch)
    _patch_agent_class(monkeypatch, _StubAgent)

    task_id = await _create_task(session_factory, _run_args())

    await run_cta_writer_task(task_id, _run_args())

    async with session_factory() as db:
        variant = await db.get(StoryVariant, "var-cta")

    assert variant is not None
    assert variant.script_breakdown["cta_text"] == "今天下单立省 50，限量 100 份！"
    # opening_hook 等其它字段保留原值。
    assert variant.script_breakdown["opening_hook"] == "原始钩子"
    assert variant.script_breakdown["total_shots"] == 3


# ---------------------------------------------------------------------------
# 3. cancel honored
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_honors_pre_execute_cancellation(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_session_maker(monkeypatch, session_factory)
    _patch_llm(monkeypatch)
    _patch_agent_class(monkeypatch, _StubAgent)

    task_id = await _create_task(session_factory, _run_args())

    async with session_factory() as db:
        store = SqlAlchemyTaskStore(db)
        await store.request_cancel(task_id)
        await db.commit()

    await run_cta_writer_task(task_id, _run_args())

    async with session_factory() as db:
        task = await db.get(GenerationTask, task_id)
        variant = await db.get(StoryVariant, "var-cta")

    assert task is not None
    assert task.status != GenerationTaskStatus.succeeded
    assert variant is not None
    assert variant.script_breakdown["cta_text"] == "原始 CTA 文案"


# ---------------------------------------------------------------------------
# 4. agent failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_marks_failed_when_agent_raises(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_session_maker(monkeypatch, session_factory)
    _patch_llm(monkeypatch)
    _patch_agent_class(monkeypatch, _RaisingAgent)

    task_id = await _create_task(session_factory, _run_args())

    with pytest.raises(RuntimeError):
        await run_cta_writer_task(task_id, _run_args())

    async with session_factory() as db:
        task = await db.get(GenerationTask, task_id)
        variant = await db.get(StoryVariant, "var-cta")

    assert task is not None
    assert task.status == GenerationTaskStatus.failed
    assert "CTA generation timed out" in (task.error or "")
    assert variant is not None
    assert variant.script_breakdown["cta_text"] == "原始 CTA 文案"


# ---------------------------------------------------------------------------
# 5. enqueue dispatch
# ---------------------------------------------------------------------------


def test_executor_registered_with_correct_task_kind_and_timeout() -> None:
    """``task_executor_registry`` 解析 ``cta_writer`` → 正确执行器与超时。"""

    executor = task_executor_registry.resolve(TASK_KIND)
    assert isinstance(executor, AbstractAsyncDelegatingExecutor)
    assert executor.task_kind == TASK_KIND == "cta_writer"
    assert executor.timeout_seconds == DEFAULT_TIMEOUT_SEC == 120.0


@pytest.mark.asyncio
async def test_dispatch_service_enqueue_cta_writer_persists_task_row(
    session_factory,
) -> None:
    """``CommerceTaskDispatchService.enqueue_cta_writer`` 链路：方法存在 + 落表。"""

    assert hasattr(CommerceTaskDispatchService, "enqueue_cta_writer")
    assert TASK_KIND_CTA_WRITER == "cta_writer"

    async with session_factory() as db:
        service = CommerceTaskDispatchService(db)
        descriptor = await service.enqueue_cta_writer(_run_args())
        await db.commit()

    assert descriptor.task_kind == TASK_KIND_CTA_WRITER
    assert descriptor.queue == "fast"
    async with session_factory() as db:
        row = await db.get(GenerationTask, descriptor.task_id)
    assert row is not None
    assert row.task_kind == "cta_writer"
    assert row.payload["task_kind"] == "cta_writer"
    assert row.payload["run_args"]["variant_id"] == "var-cta"
    assert row.payload["run_args"]["hardness"] == "medium"
