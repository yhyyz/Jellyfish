"""``shot_subtitle_render_worker`` 功能性测试（P3 W18 T18-5）。

测试覆盖（≥6 cases）：

1. ``task_executor_registry.resolve("shot_subtitle_render")`` 命中本 worker 工厂；
2. 工厂构造的 executor ``timeout_seconds`` 等于 plan 约定的 120s；
3. 空 ``shot_id`` / ``style_id`` → 立刻 ``ValueError``；
4. ``style_id`` 不存在 → 抛 LookupError，状态置 ``failed``；
5. happy-path：渲染成 ``.ass`` 文件 + 落 SubtitleTrack，结果 dict 字段齐全；
6. cancel 短路：``cancel_if_requested_async`` 返回 True 时不写 SubtitleTrack；
7. SubtitleStyle 安全区违规（margin_v 太小）→ result.warnings 非空。

测试架构：文件型 SQLite + Base.metadata.create_all + monkeypatch async_session_maker；
storage.upload_file 用 mock 替换避免真实 S3 调用。
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
from app.core.storage import StoredFileInfo
from app.models.studio import (
    Chapter,
    Project,
    ProjectStyle,
    Shot,
    ShotStatus,
)
from app.models.subtitle import SubtitleStyle, SubtitleTrack
from app.models.task import GenerationDeliveryMode, GenerationTask, GenerationTaskStatus
from app.models.types import SubtitleAlignment, SubtitleFormat, SubtitleSource
from app.services.studio import shot_subtitle_render_worker as worker_mod
from app.services.studio.shot_subtitle_render_worker import (
    DEFAULT_TIMEOUT_SECONDS,
    TASK_KIND,
    build_shot_subtitle_render_executor,
    run_shot_subtitle_render_task,
)
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_registry import task_executor_registry


_PROJECT_ID = "proj-w18-1"
_CHAPTER_ID = "chap-w18-1"
_SHOT_ID = "shot-w18-1"
_STYLE_ID = "douyin_default"
_TASK_ID_HAPPY = "task-w18-happy"


@pytest.fixture
def session_local(tmp_path) -> Generator[async_sessionmaker[AsyncSession], None, None]:
    """文件型 SQLite + Base.metadata.create_all 的 async sessionmaker。"""

    db_path = tmp_path / "subtitle-render.db"
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
    """把 worker 模块内的 ``async_session_maker`` 替换为测试 sessionmaker。"""

    monkeypatch.setattr(worker_mod, "async_session_maker", session_local)
    return session_local


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _install_no_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    """``cancel_if_requested_async`` 永远返回 False。"""

    async def _never(*_: Any, **__: Any) -> bool:
        return False

    monkeypatch.setattr(worker_mod, "cancel_if_requested_async", _never)


def _install_always_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    """``cancel_if_requested_async`` 永远返回 True。"""

    async def _always(*_: Any, **__: Any) -> bool:
        return True

    monkeypatch.setattr(worker_mod, "cancel_if_requested_async", _always)


def _install_fake_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """跳过真实 S3，``upload_file`` 直接返回 fake StoredFileInfo。"""

    async def _upload(*, key: str, **_: Any) -> StoredFileInfo:
        return StoredFileInfo(
            key=key,
            url=f"https://cdn.example.com/{key}",
            size=512,
            content_type="text/x-ssa",
        )

    monkeypatch.setattr(worker_mod.storage, "upload_file", _upload)


async def _seed_project_chapter_shot(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """种入 Project / Chapter / Shot 骨架，让 SubtitleTrack.shot_id FK 通过。"""

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
            )
        )
        await db.commit()


async def _seed_subtitle_style(
    sm: async_sessionmaker[AsyncSession],
    *,
    style_id: str = _STYLE_ID,
    margin_v: int = 200,
) -> None:
    """种入一行 SubtitleStyle 让 worker 加载。"""

    async with sm() as db:
        db.add(
            SubtitleStyle(
                id=style_id,
                name="测试样式",
                description="",
                language_code="zh-CN",
                format=SubtitleFormat.ass,
                font_family="Source Han Sans CN Heavy",
                font_fallback_chain=["Source Han Sans CN Heavy", "Arial"],
                font_size=64,
                primary_colour="&H00FFFFFF",
                secondary_colour="&H00FFFF00",
                outline_colour="&H00000000",
                back_colour="&H80000000",
                bold=True,
                italic=False,
                border_style=1,
                outline=3.0,
                shadow=1.0,
                alignment=SubtitleAlignment.bottom_center,
                margin_l=60,
                margin_r=60,
                margin_v=margin_v,
                play_res_x=1080,
                play_res_y=1920,
                is_system=True,
                sort_order=0,
            )
        )
        await db.commit()


async def _seed_generation_task(
    sm: async_sessionmaker[AsyncSession],
    *,
    task_id: str,
    cancel_requested: bool = False,
) -> None:
    """种一行 ``GenerationTask`` 行。"""

    async with sm() as db:
        db.add(
            GenerationTask(
                id=task_id,
                mode=GenerationDeliveryMode.async_polling,
                task_kind=TASK_KIND,
                status=GenerationTaskStatus.pending,
                progress=0,
                payload={"task_kind": TASK_KIND, "run_args": {}},
                result=None,
                error="",
                cancel_requested=cancel_requested,
            )
        )
        await db.commit()


# ---------------------------------------------------------------------------
# 1. 注册元数据
# ---------------------------------------------------------------------------


def test_executor_registered_with_shot_subtitle_render_task_kind() -> None:
    """``task_executor_registry.resolve("shot_subtitle_render")`` 应命中本 worker。"""

    executor = task_executor_registry.resolve(TASK_KIND)
    assert isinstance(executor, AbstractAsyncDelegatingExecutor)
    assert executor.task_kind == TASK_KIND


def test_executor_timeout_set_to_120s() -> None:
    """fast 队列超时上限：120s（纯计算 + 一次 minio 上传）。"""

    executor = build_shot_subtitle_render_executor()
    assert executor.timeout_seconds == DEFAULT_TIMEOUT_SECONDS == 120.0
    assert executor.task_kind == TASK_KIND == "shot_subtitle_render"


# ---------------------------------------------------------------------------
# 2. run_args 校验
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_rejects_empty_shot_id() -> None:
    with pytest.raises(ValueError, match="shot_id"):
        await run_shot_subtitle_render_task(
            "task-x",
            {"shot_id": "", "style_id": _STYLE_ID, "word_timestamps": []},
        )


@pytest.mark.asyncio
async def test_runner_rejects_empty_style_id() -> None:
    with pytest.raises(ValueError, match="style_id"):
        await run_shot_subtitle_render_task(
            "task-x",
            {"shot_id": _SHOT_ID, "style_id": "", "word_timestamps": []},
        )


@pytest.mark.asyncio
async def test_runner_marks_failed_when_style_id_not_found(
    patched_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``style_id`` 不存在：worker 走 hotfix-4 失败路径，状态置 ``failed``。"""

    _install_no_cancel(monkeypatch)
    _install_fake_storage(monkeypatch)

    await _seed_project_chapter_shot(patched_session)

    task_id = "task-w18-missing-style"
    await _seed_generation_task(patched_session, task_id=task_id)

    with pytest.raises(LookupError):
        await run_shot_subtitle_render_task(
            task_id,
            {
                "shot_id": _SHOT_ID,
                "style_id": "nonexistent-style",
                "word_timestamps": [],
            },
        )

    async with patched_session() as db:
        task_row = await db.get(GenerationTask, task_id)
        assert task_row is not None
        assert task_row.status == GenerationTaskStatus.failed
        assert "nonexistent-style" in (task_row.error or "")


# ---------------------------------------------------------------------------
# 3. happy-path：完整渲染 + 落 SubtitleTrack
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_renders_ass_and_persists_subtitle_track(
    patched_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """happy-path：渲染 .ass + 落 SubtitleTrack + result 字段齐全。"""

    _install_no_cancel(monkeypatch)
    _install_fake_storage(monkeypatch)

    await _seed_project_chapter_shot(patched_session)
    await _seed_subtitle_style(patched_session)
    await _seed_generation_task(patched_session, task_id=_TASK_ID_HAPPY)

    word_timestamps = [
        {"text": "你", "begin_ms": 0, "end_ms": 300},
        {"text": "好", "begin_ms": 300, "end_ms": 600},
        {"text": "世", "begin_ms": 600, "end_ms": 900},
        {"text": "界", "begin_ms": 900, "end_ms": 1200},
    ]

    await run_shot_subtitle_render_task(
        _TASK_ID_HAPPY,
        {
            "shot_id": _SHOT_ID,
            "style_id": _STYLE_ID,
            "word_timestamps": word_timestamps,
            "language_code": "zh-CN",
            "source": SubtitleSource.tts_word_timestamps.value,
        },
    )

    async with patched_session() as db:
        task_row = await db.get(GenerationTask, _TASK_ID_HAPPY)
        assert task_row is not None
        assert task_row.status == GenerationTaskStatus.succeeded
        assert task_row.progress == 100
        assert isinstance(task_row.result, dict)
        result = task_row.result
        assert result["style_id"] == _STYLE_ID
        assert result["language_code"] == "zh-CN"
        assert result["source"] == "tts_word_timestamps"
        assert result["cue_count"] >= 1
        assert result["duration_ms"] == 1200
        assert "subtitle_track_id" in result
        assert "file_id" in result

        # SubtitleTrack 行已落库，FK 字段齐全。
        track = await db.get(SubtitleTrack, result["subtitle_track_id"])
        assert track is not None
        assert track.shot_id == _SHOT_ID
        assert track.style_id == _STYLE_ID
        assert track.file_id == result["file_id"]
        assert track.duration_ms == 1200


# ---------------------------------------------------------------------------
# 4. cancel checkpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_short_circuits_on_cancel_before_render(
    patched_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """首次 cancel 检查为 True 时，不应写 SubtitleTrack。"""

    _install_always_cancel(monkeypatch)
    _install_fake_storage(monkeypatch)

    await _seed_project_chapter_shot(patched_session)
    await _seed_subtitle_style(patched_session)

    task_id = "task-w18-cancel"
    await _seed_generation_task(patched_session, task_id=task_id, cancel_requested=True)

    await run_shot_subtitle_render_task(
        task_id,
        {
            "shot_id": _SHOT_ID,
            "style_id": _STYLE_ID,
            "word_timestamps": [
                {"text": "你", "begin_ms": 0, "end_ms": 300},
            ],
        },
    )

    async with patched_session() as db:
        rows = (
            await db.execute(
                select(SubtitleTrack).where(SubtitleTrack.shot_id == _SHOT_ID)
            )
        ).scalars().all()
        assert rows == []


# ---------------------------------------------------------------------------
# 5. 安全区违规 → warnings 非空
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_emits_safe_zone_warnings_when_style_violates_floor(
    patched_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SubtitleStyle 的 margin_v 低于平台下限时，result.warnings 非空。"""

    _install_no_cancel(monkeypatch)
    _install_fake_storage(monkeypatch)

    await _seed_project_chapter_shot(patched_session)
    # margin_v=80 远低于抖音 180 下限。
    await _seed_subtitle_style(patched_session, margin_v=80)

    task_id = "task-w18-warn"
    await _seed_generation_task(patched_session, task_id=task_id)

    await run_shot_subtitle_render_task(
        task_id,
        {
            "shot_id": _SHOT_ID,
            "style_id": _STYLE_ID,
            "word_timestamps": [
                {"text": "测", "begin_ms": 0, "end_ms": 300},
                {"text": "试", "begin_ms": 300, "end_ms": 600},
            ],
        },
    )

    async with patched_session() as db:
        task_row = await db.get(GenerationTask, task_id)
        assert task_row is not None
        assert task_row.status == GenerationTaskStatus.succeeded
        warnings = (task_row.result or {}).get("warnings") or []
        assert any("margin_v" in str(w) for w in warnings)
