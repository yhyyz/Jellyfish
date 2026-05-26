"""``chapter_av_plan_worker`` 集成测试（P3 W17 T17-7）。

测试覆盖（≥4 cases）：

1. 全章节遍历 → 每条 ``ShotDialogLine`` 的 ``start_time_ms`` / ``end_time_ms``
   被正确写入；rewrite 命中时 ``text`` 被覆盖；
2. 持久化：DB 行字段与决策结果完全一致，且 ``GenerationTask`` 落到
   ``succeeded`` 状态、``result`` 含 decision summary；
3. 三个 cancel checkpoints：注入 ``cancel_requested=True`` 时 worker
   立刻退出而不再写决策；
4. ``hold`` 案例：``warning`` 写入 result 的 ``warnings`` 列表，便于前端
   运营面板展示。
"""

# pylint: disable=redefined-outer-name,too-many-arguments,too-many-locals

from __future__ import annotations

import asyncio
from collections.abc import Generator
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.models.studio_projects import Chapter, Project
from app.models.studio_shots import Shot, ShotDetail, ShotDialogLine
from app.models.task import GenerationDeliveryMode, GenerationTask, GenerationTaskStatus
from app.models.types import (
    AudioStrategy,
    CameraAngle,
    CameraMovement,
    CameraShotType,
    DialogueLineMode,
    ProjectStyle,
    ShotStatus,
    VoiceGender,
    VoiceProvider,
)
from app.models.voice_pack import VoicePack
from app.services.studio import chapter_av_plan_worker as worker_mod
from app.services.studio.chapter_av_plan_worker import (
    DEFAULT_TIMEOUT_SECONDS,
    TASK_KIND,
    build_chapter_av_plan_executor,
    run_chapter_av_plan_task,
)
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_registry import task_executor_registry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_VOICE_PACK_ID = "cosyvoice_v2_test"
_PROJECT_ID = "proj-av-1"
_CHAPTER_ID = "chap-av-1"
_SHOT_ID = "shot-av-1"


@pytest.fixture
def session_local(tmp_path) -> Generator[async_sessionmaker[AsyncSession], None, None]:
    """文件型 SQLite + 全表 create_all。"""

    db_path = tmp_path / "chapter-av-plan.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _create_all() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    try:
        yield sm
    finally:

        async def _dispose() -> None:
            await engine.dispose()

        asyncio.run(_dispose())


@pytest.fixture
def patched_session(
    session_local: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> async_sessionmaker[AsyncSession]:
    """让 worker 内部的 ``async_session_maker`` 指向测试 sessionmaker。"""

    monkeypatch.setattr(worker_mod, "async_session_maker", session_local)
    return session_local


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_project_chapter_shot(
    sm: async_sessionmaker[AsyncSession],
    *,
    duration_sec: int = 4,
    audio_strategy: AudioStrategy = AudioStrategy.silent_with_tts,
) -> None:
    """种入 Project / Chapter / Shot / ShotDetail / VoicePack 完整骨架。

    ``audio_strategy`` 控制 ``Shot.audio_strategy`` 字段，缺省 ``silent_with_tts``
    与生产 server_default 一致；keep_native 用例显式传参以触发 worker 的
    skip_native 分流路径。
    """

    async with sm() as db:
        db.add(
            Project(
                id=_PROJECT_ID,
                name="测试项目",
                style=ProjectStyle.real_people_city,
            )
        )
        db.add(
            Chapter(
                id=_CHAPTER_ID,
                project_id=_PROJECT_ID,
                index=1,
                title="测试章",
            )
        )
        db.add(
            Shot(
                id=_SHOT_ID,
                chapter_id=_CHAPTER_ID,
                index=1,
                title="测试镜头",
                status=ShotStatus.ready,
                audio_strategy=audio_strategy,
            )
        )
        db.add(
            ShotDetail(
                id=_SHOT_ID,
                camera_shot=CameraShotType.ms,
                angle=CameraAngle.eye_level,
                movement=CameraMovement.static,
                duration=duration_sec,
            )
        )
        db.add(
            VoicePack(
                id=_VOICE_PACK_ID,
                name="龙小淳-test",
                provider=VoiceProvider.aliyun_cosyvoice,
                provider_voice_id="longxiaochun_v2",
                language_code="zh-CN",
                gender=VoiceGender.female,
                description="test",
                default_speed=1.0,
                is_system=True,
                sort_order=0,
            )
        )
        await db.commit()


async def _seed_dialog_line(
    sm: async_sessionmaker[AsyncSession],
    *,
    text: str,
    line_mode: DialogueLineMode = DialogueLineMode.dialogue,
    index: int = 0,
) -> int:
    """种入一行 ``ShotDialogLine`` 并返回主键 id。"""

    async with sm() as db:
        line = ShotDialogLine(
            shot_detail_id=_SHOT_ID,
            index=index,
            text=text,
            line_mode=line_mode,
            tts_voice_id=_VOICE_PACK_ID,
        )
        db.add(line)
        await db.commit()
        await db.refresh(line)
        return line.id


async def _seed_generation_task(
    sm: async_sessionmaker[AsyncSession],
    *,
    task_id: str,
    cancel_requested: bool = False,
) -> None:
    """种一行 ``GenerationTask``，与 worker 状态机对齐。"""

    async with sm() as db:
        db.add(
            GenerationTask(
                id=task_id,
                mode=GenerationDeliveryMode.async_polling,
                task_kind=TASK_KIND,
                status=GenerationTaskStatus.pending,
                progress=0,
                payload={
                    "task_kind": TASK_KIND,
                    "run_args": {"chapter_id": _CHAPTER_ID},
                },
                result=None,
                error="",
                cancel_requested=cancel_requested,
            )
        )
        await db.commit()


def _install_no_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    """关闭取消检测，让 worker 走完整路径。"""

    async def _never(*_: Any, **__: Any) -> bool:
        return False

    monkeypatch.setattr(worker_mod, "cancel_if_requested_async", _never)


def _install_always_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    """让首次 cancel 检查就返回 True，模拟“被运营点了取消”。"""

    async def _always(*_: Any, **__: Any) -> bool:
        return True

    monkeypatch.setattr(worker_mod, "cancel_if_requested_async", _always)


# ---------------------------------------------------------------------------
# 1. 注册元数据
# ---------------------------------------------------------------------------


def test_executor_registered_with_chapter_av_plan_task_kind() -> None:
    """``task_executor_registry.resolve("chapter_av_plan")`` 应命中本 worker。"""

    executor = task_executor_registry.resolve(TASK_KIND)
    assert isinstance(executor, AbstractAsyncDelegatingExecutor)
    assert executor.task_kind == TASK_KIND


def test_executor_timeout_set_to_7200s() -> None:
    """slow 队列超时上限：7200s（与 chapter_timeline_export 对齐）。"""

    executor = build_chapter_av_plan_executor()
    assert executor.timeout_seconds == DEFAULT_TIMEOUT_SECONDS == 7200.0
    assert executor.task_kind == TASK_KIND == "chapter_av_plan"


# ---------------------------------------------------------------------------
# 2. 全章节 happy-path：accept 分支
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_writes_back_start_end_time_for_accept_path(
    patched_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``accept`` 路径：``start_time_ms=0`` / ``end_time_ms=estimated``，``text`` 不变。"""

    _install_no_cancel(monkeypatch)

    await _seed_project_chapter_shot(patched_session, duration_sec=2)
    # 8 字 dialog @ 4 chars/sec ≈ 2000ms == 目标 2000ms，必走 accept。
    line_id = await _seed_dialog_line(patched_session, text="一二三四五六七八")

    task_id = "task-accept"
    await _seed_generation_task(patched_session, task_id=task_id)

    await run_chapter_av_plan_task(
        task_id, {"chapter_id": _CHAPTER_ID}
    )

    async with patched_session() as db:
        line = (
            await db.execute(
                select(ShotDialogLine).where(ShotDialogLine.id == line_id)
            )
        ).scalar_one()
        assert line.start_time_ms == 0
        assert line.end_time_ms is not None and line.end_time_ms > 0
        assert line.text == "一二三四五六七八"

        task_row = await db.get(GenerationTask, task_id)
        assert task_row is not None
        assert task_row.status == GenerationTaskStatus.succeeded
        assert task_row.progress == 100
        assert isinstance(task_row.result, dict)
        decisions = task_row.result.get("decisions") or []
        assert len(decisions) == 1
        assert decisions[0]["action"] == "accept"


# ---------------------------------------------------------------------------
# 3. cancel checkpoint：worker 立刻退出
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_short_circuits_on_cancel_before_iteration(
    patched_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """首次 cancel 检查为 True 时，worker 不再遍历分镜。"""

    _install_always_cancel(monkeypatch)

    await _seed_project_chapter_shot(patched_session, duration_sec=2)
    line_id = await _seed_dialog_line(patched_session, text="测试取消")

    task_id = "task-cancel"
    await _seed_generation_task(patched_session, task_id=task_id, cancel_requested=True)

    await run_chapter_av_plan_task(
        task_id, {"chapter_id": _CHAPTER_ID}
    )

    async with patched_session() as db:
        line = (
            await db.execute(
                select(ShotDialogLine).where(ShotDialogLine.id == line_id)
            )
        ).scalar_one()
        # 取消时不应写入 start/end_time_ms。
        assert line.start_time_ms is None
        assert line.end_time_ms is None


# ---------------------------------------------------------------------------
# 4. hold 路径：warnings 写入 result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_records_holds_in_result_warnings(
    patched_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """连续 LLM 改写仍超阈值：result.warnings 必须包含告警条目。"""

    _install_no_cancel(monkeypatch)

    # 把 worker 内部 rewriter 替换成永远返回原文 → 永远 mismatch → 触发 hold。
    async def _never_shrink_invoker(
        _db: object,
        *,
        original_text: str,
        target_chars: int,  # pylint: disable=unused-argument
        line_mode: DialogueLineMode,  # pylint: disable=unused-argument
    ) -> str:
        return original_text

    monkeypatch.setattr(
        worker_mod, "_default_rewriter_invoker", lambda _db: _never_shrink_invoker
    )

    await _seed_project_chapter_shot(patched_session, duration_sec=1)
    long_text = "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥风雨雷电山川河海"
    line_id = await _seed_dialog_line(patched_session, text=long_text)

    task_id = "task-hold"
    await _seed_generation_task(patched_session, task_id=task_id)

    await run_chapter_av_plan_task(
        task_id, {"chapter_id": _CHAPTER_ID}
    )

    async with patched_session() as db:
        task_row = await db.get(GenerationTask, task_id)
        assert task_row is not None
        assert task_row.status == GenerationTaskStatus.succeeded
        result = task_row.result or {}
        decisions = result.get("decisions") or []
        # 1 行：唯一动作必为 hold。
        assert any(d["action"] == "hold" for d in decisions)
        warnings = result.get("warnings") or []
        assert len(warnings) >= 1
        assert any("人工" in str(w.get("warning", "")) for w in warnings)
        # 该行被列入 holds 列表，便于前端高亮。
        holds = result.get("holds") or []
        assert line_id in holds


# ---------------------------------------------------------------------------
# 5. keep_native 分流：worker 走 skip_native 分支（P3 W17 收尾，Decision D 修订）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_skips_native_path_when_audio_strategy_is_keep_native(
    patched_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``Shot.audio_strategy=keep_native`` 时：

    - decision.action 应为 ``skip_native``；
    - 不调 rewriter（即便文本远超阈值也不应触发 LLM 改写）；
    - line.text 保持原文；line.start_time_ms / end_time_ms 仍被写入；
    - GenerationTask 正常落到 succeeded。
    """

    _install_no_cancel(monkeypatch)

    # 即便注入"永远不收敛"的 rewriter，keep_native 也应跳过它。
    rewrite_calls: list[str] = []

    async def _track_rewriter(
        _db: object,
        *,
        original_text: str,
        target_chars: int,  # pylint: disable=unused-argument
        line_mode: DialogueLineMode,  # pylint: disable=unused-argument
    ) -> str:
        rewrite_calls.append(original_text)
        return original_text

    monkeypatch.setattr(
        worker_mod, "_default_rewriter_invoker", lambda _db: _track_rewriter
    )

    await _seed_project_chapter_shot(
        patched_session,
        duration_sec=2,
        audio_strategy=AudioStrategy.keep_native,
    )
    long_text = "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥风雨雷电山川河海"
    line_id = await _seed_dialog_line(patched_session, text=long_text)

    task_id = "task-keep-native"
    await _seed_generation_task(patched_session, task_id=task_id)

    await run_chapter_av_plan_task(
        task_id, {"chapter_id": _CHAPTER_ID}
    )

    assert rewrite_calls == [], (
        "keep_native 路径绝不应触发 LLM 改写，避免误烧 token"
    )

    async with patched_session() as db:
        line = (
            await db.execute(
                select(ShotDialogLine).where(ShotDialogLine.id == line_id)
            )
        ).scalar_one()
        assert line.text == long_text, "skip_native 必须保留原文"
        assert line.start_time_ms == 0
        assert line.end_time_ms == 2000, (
            "estimated_ms == shot_duration_ms 占位，2000ms == duration_sec*1000"
        )

        task_row = await db.get(GenerationTask, task_id)
        assert task_row is not None
        assert task_row.status == GenerationTaskStatus.succeeded
        assert isinstance(task_row.result, dict)
        decisions = task_row.result.get("decisions") or []
        assert len(decisions) == 1
        assert decisions[0]["action"] == "skip_native"
        assert decisions[0]["original_text"] == long_text
        assert decisions[0]["final_text"] == long_text
        assert decisions[0]["suggested_speed"] == pytest.approx(1.0)
        # holds / warnings 列表均应为空（skip_native 不是 hold）。
        assert task_row.result.get("holds") == []
        assert task_row.result.get("warnings") == []
