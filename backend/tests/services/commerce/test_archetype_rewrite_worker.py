"""``archetype_rewrite_worker`` 任务执行器测试（W12 P2 TDD backfill）。

覆盖：

1. lifecycle：mock agent → task running → succeeded、progress=100、
   ``StoryVariant.archetype`` 列被刷新；
2. payload mutation：``script_breakdown`` 被整段替换为改写后脚本，
   ``shots`` 数量与 ``brand_mention_count`` 与原脚本一致；
3. cancel honored：pre-execute cancel 让 worker 早退；
4. agent failure：agent 抛错（结构破坏 / LLM 超时）→ task 失败、
   ``error`` 含原异常文本；
5. enqueue dispatch：registry 注册 + ``enqueue_archetype_rewrite`` 链路存在。
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

from app.core.contracts.story import Shot, StoryScript
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
from app.services.commerce.archetype_rewrite_worker import (
    DEFAULT_TIMEOUT_SEC,
    TASK_KIND,
    run_archetype_rewrite_task,
)
from app.services.commerce.task_dispatch import (
    CommerceTaskDispatchService,
    TASK_KIND_ARCHETYPE_REWRITE,
)
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_registry import task_executor_registry


# ---------------------------------------------------------------------------
# Fixture：file-backed SQLite + 全 FK 行 + 已落 script_breakdown
# ---------------------------------------------------------------------------


def _make_shot(*, shot_id: str, dialog: str, is_brand_mention: bool = False) -> Shot:
    return Shot(
        id=shot_id,
        duration_sec=5.0,
        function="setup",
        shot_type="medium",
        camera_angle="eye_level",
        camera_movement="static",
        dialog=dialog,
        narration=None,
        product_focus_level="subtle",
        is_punchline=False,
        is_brand_mention=is_brand_mention,
        notes=None,
    )


def _make_script(*, opening_hook: str = "原始钩子") -> StoryScript:
    return StoryScript(
        total_duration_sec=20.0,
        total_shots=4,
        formula_id="formula-1",
        shots=[
            _make_shot(shot_id="s1", dialog="镜 1 原始对白"),
            _make_shot(shot_id="s2", dialog="镜 2 原始对白", is_brand_mention=True),
            _make_shot(shot_id="s3", dialog="镜 3 原始对白"),
            _make_shot(shot_id="s4", dialog="镜 4 原始对白"),
        ],
        opening_hook=opening_hook,
        cta_text="原始 CTA",
        brand_mention_count=1,
    )


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    db_path = tmp_path / "archetype-rewrite-worker.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_local = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    base_script = _make_script()

    async with session_local() as setup_db:
        setup_db.add(
            PromptTemplate(
                id="tpl-arch-1",
                category=PromptCategory.archetype_voice_rewriter,
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
                prompt_template_id="tpl-arch-1",
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
                id="var-arch",
                project_id="proj-1",
                chapter_id="chap-1",
                formula_id="formula-1",
                script_full_text="占位脚本",
                script_breakdown=base_script.model_dump(mode="json"),
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
    """canned ``StoryScript`` 改写结果的最小 agent stub。

    ``a_rewrite_voice`` 直接返回结构保留 + 文本改写后的脚本，模拟 W12-T3
    Agent 在通过 ``validate_structure_preserved`` / ``validate_words_to_avoid``
    后的合法返回。
    """

    def __init__(self, model: Any, *, rewritten: StoryScript | None = None) -> None:
        self.model = model
        self._rewritten = rewritten or _make_script(opening_hook="hero 化的钩子").model_copy(
            update={
                "shots": [
                    _make_shot(shot_id="s1", dialog="hero 化镜 1"),
                    _make_shot(shot_id="s2", dialog="hero 化镜 2", is_brand_mention=True),
                    _make_shot(shot_id="s3", dialog="hero 化镜 3"),
                    _make_shot(shot_id="s4", dialog="hero 化镜 4"),
                ],
                "cta_text": "hero 化的 CTA",
            }
        )
        self.calls: list[dict[str, Any]] = []

    async def a_rewrite_voice(  # pylint: disable=redefined-builtin
        self, *, vars  # noqa: A002
    ) -> StoryScript:
        self.calls.append({"vars": vars})
        return self._rewritten


class _RaisingAgent:
    def __init__(self, model: Any) -> None:
        self.model = model

    async def a_rewrite_voice(  # pylint: disable=redefined-builtin
        self, *, vars  # noqa: A002
    ) -> StoryScript:
        raise ValueError("shot s1 field id changed: 's1' -> 's1_renamed'")


def _patch_session_maker(monkeypatch, session_local) -> None:
    monkeypatch.setattr(
        "app.services.commerce.archetype_rewrite_worker.async_session_maker",
        session_local,
    )


def _patch_llm(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.commerce.archetype_rewrite_worker.build_default_text_llm_sync",
        lambda *_args, **_kwargs: MagicMock(name="LLM-stub"),
    )


def _patch_agent_class(monkeypatch, agent_cls) -> None:
    monkeypatch.setattr(
        "app.services.commerce.archetype_rewrite_worker.ArchetypeVoiceRewriterAgent",
        agent_cls,
    )


def _run_args() -> dict[str, Any]:
    return {
        "variant_id": "var-arch",
        "archetype": "hero",
        "archetype_description": "hero 人格的自然语言描述",
        "tone_grid": {"formality": 6, "energy": 8, "warmth": 5},
        "words_to_avoid": ["最", "第一"],
        "preferred_vocab": ["真诚", "可靠"],
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
async def test_runner_lifecycle_succeeds_and_writes_archetype_column(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """合法 run_args + stub agent → task succeeded、``variant.archetype`` 落库。"""

    _patch_session_maker(monkeypatch, session_factory)
    _patch_llm(monkeypatch)
    _patch_agent_class(monkeypatch, _StubAgent)

    task_id = await _create_task(session_factory, _run_args())

    await run_archetype_rewrite_task(task_id, _run_args())

    async with session_factory() as db:
        task = await db.get(GenerationTask, task_id)
        variant = await db.get(StoryVariant, "var-arch")

    assert task is not None
    assert task.status == GenerationTaskStatus.succeeded
    assert task.progress == 100
    assert task.result is not None
    assert task.result["variant_id"] == "var-arch"
    assert task.result["archetype"] == "hero"
    assert task.result["shot_count"] == 4
    assert task.result["brand_mention_count"] == 1

    assert variant is not None
    assert variant.archetype == "hero"


# ---------------------------------------------------------------------------
# 2. payload mutation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_replaces_script_breakdown_with_rewritten_dialog(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """worker 成功后：``script_breakdown`` 被整段替换；shots / brand_mention 保留。"""

    _patch_session_maker(monkeypatch, session_factory)
    _patch_llm(monkeypatch)
    _patch_agent_class(monkeypatch, _StubAgent)

    task_id = await _create_task(session_factory, _run_args())

    await run_archetype_rewrite_task(task_id, _run_args())

    async with session_factory() as db:
        variant = await db.get(StoryVariant, "var-arch")

    assert variant is not None
    breakdown = variant.script_breakdown
    assert breakdown["opening_hook"] == "hero 化的钩子"
    assert breakdown["cta_text"] == "hero 化的 CTA"
    # shots 数量与 brand_mention_count 与原脚本一致（结构保留）。
    assert len(breakdown["shots"]) == 4
    assert breakdown["brand_mention_count"] == 1
    # 每个 shot 对白都被改写。
    assert all(shot["dialog"].startswith("hero 化") for shot in breakdown["shots"])


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

    await run_archetype_rewrite_task(task_id, _run_args())

    async with session_factory() as db:
        task = await db.get(GenerationTask, task_id)
        variant = await db.get(StoryVariant, "var-arch")

    assert task is not None
    assert task.status != GenerationTaskStatus.succeeded
    # archetype 列没被改写，证明 worker 在 LLM 调用前就早退。
    assert variant is not None
    assert variant.archetype is None
    assert variant.script_breakdown["opening_hook"] == "原始钩子"


# ---------------------------------------------------------------------------
# 4. agent failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_marks_failed_when_agent_raises(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """agent 抛 ``ValueError``（结构破坏）→ task 状态 failed、error 含异常消息。"""

    _patch_session_maker(monkeypatch, session_factory)
    _patch_llm(monkeypatch)
    _patch_agent_class(monkeypatch, _RaisingAgent)

    task_id = await _create_task(session_factory, _run_args())

    with pytest.raises(ValueError):
        await run_archetype_rewrite_task(task_id, _run_args())

    async with session_factory() as db:
        task = await db.get(GenerationTask, task_id)
        variant = await db.get(StoryVariant, "var-arch")

    assert task is not None
    assert task.status == GenerationTaskStatus.failed
    assert "shot s1" in (task.error or "")
    # variant 未被改写。
    assert variant is not None
    assert variant.archetype is None
    assert variant.script_breakdown["opening_hook"] == "原始钩子"


# ---------------------------------------------------------------------------
# 5. enqueue dispatch
# ---------------------------------------------------------------------------


def test_executor_registered_with_correct_task_kind_and_timeout() -> None:
    """``task_executor_registry`` 解析 ``archetype_rewrite`` → 正确执行器与超时。"""

    executor = task_executor_registry.resolve(TASK_KIND)
    assert isinstance(executor, AbstractAsyncDelegatingExecutor)
    assert executor.task_kind == TASK_KIND == "archetype_rewrite"
    assert executor.timeout_seconds == DEFAULT_TIMEOUT_SEC == 600.0


@pytest.mark.asyncio
async def test_dispatch_service_enqueue_archetype_rewrite_persists_task_row(
    session_factory,
) -> None:
    """``CommerceTaskDispatchService.enqueue_archetype_rewrite`` 链路：
    方法存在 + ``GenerationTask`` 行落库。"""

    assert hasattr(CommerceTaskDispatchService, "enqueue_archetype_rewrite")
    assert TASK_KIND_ARCHETYPE_REWRITE == "archetype_rewrite"

    async with session_factory() as db:
        service = CommerceTaskDispatchService(db)
        descriptor = await service.enqueue_archetype_rewrite(_run_args())
        await db.commit()

    assert descriptor.task_kind == TASK_KIND_ARCHETYPE_REWRITE
    assert descriptor.queue == "fast"
    async with session_factory() as db:
        row = await db.get(GenerationTask, descriptor.task_id)
    assert row is not None
    assert row.task_kind == "archetype_rewrite"
    assert row.payload["task_kind"] == "archetype_rewrite"
    assert row.payload["run_args"]["variant_id"] == "var-arch"
    assert row.payload["run_args"]["archetype"] == "hero"
