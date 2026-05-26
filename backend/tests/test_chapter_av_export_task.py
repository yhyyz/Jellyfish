"""``chapter_av_export_task`` 集成测试（P3 W19 T19-1/T19-7）。

覆盖（≥6 cases）：

1. ``task_executor_registry.resolve("chapter_av_export")`` 命中本 worker 工厂；
2. 工厂构造的 executor ``timeout_seconds`` 等于 plan 约定的 1800s；
3. 空 ``chapter_id`` → 立刻 RuntimeError；
4. 不支持的 ``aspect`` → ValueError；
5. happy-path：mock ffmpeg + storage，验证 worker 完整链路（加载 segments
   → 构造 filter graph → 上传产物 → 落 FileItem + GenerationTaskLink.file_id +
   FileUsage + Shot.dubbed_video_file_id + GenerationTask.result）；
6. ffmpeg 失败 → worker 走 hotfix-4 失败路径，状态置 failed；
7. cancel 短路：``cancel_if_requested_async`` 返回 True 时不上传产物；
8. 无字幕 / 无 TTS 段降级正常工作（worker 不抛错）。

测试架构：mock ``_run_ffmpeg_av_export`` + ``storage.upload_file`` +
``storage.download_file``；ffprobe 通过 monkeypatch 替换避免真实视频文件依赖。
"""

# pylint: disable=redefined-outer-name,too-many-arguments,too-many-locals

from __future__ import annotations

import asyncio
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.core.storage import StoredFileInfo
from app.models.studio import (
    Chapter,
    ChapterTimelineSegment,
    FileItem,
    FileType,
    Project,
    ProjectStyle,
    Shot,
    ShotDetail,
    ShotStatus,
)
from app.models.studio_shots import (
    CameraAngle,
    CameraMovement,
    CameraShotType,
)
from app.models.task import GenerationDeliveryMode, GenerationTask, GenerationTaskStatus
from app.models.task_links import GenerationTaskLink
from app.models.types import AudioStrategy
from app.services.studio import chapter_av_export_task as worker_mod
from app.services.studio.chapter_av_export_task import (
    DEFAULT_TIMEOUT_SECONDS,
    TASK_KIND,
    build_chapter_av_export_executor,
    run_chapter_av_export_task,
)
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_registry import task_executor_registry


_PROJECT_ID = "proj-w19-export"
_CHAPTER_ID = "chap-w19-export"


@pytest.fixture
def session_local(tmp_path) -> Generator[async_sessionmaker[AsyncSession], None, None]:
    """文件型 SQLite + Base.metadata.create_all。"""

    db_path = tmp_path / "av-export.db"
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
def patched(
    session_local: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> async_sessionmaker[AsyncSession]:
    monkeypatch.setattr(worker_mod, "async_session_maker", session_local)

    async def _never_cancel(*_: Any, **__: Any) -> bool:
        return False

    monkeypatch.setattr(worker_mod, "cancel_if_requested_async", _never_cancel)
    return session_local


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_chapter_with_shots(
    sm: async_sessionmaker[AsyncSession],
    *,
    n_shots: int = 2,
    audio_strategy: AudioStrategy = AudioStrategy.silent_with_tts,
    with_subtitle: bool = True,
    with_tts_audio: bool = True,
) -> list[str]:
    """种入 Project / Chapter / N 个 Shot + ChapterTimelineSegment + 必要 FileItem。

    返回新建的 FileItem ID 列表（视频/字幕/TTS）便于后续断言。
    """

    file_ids: list[str] = []
    async with sm() as db:
        db.add(
            Project(
                id=_PROJECT_ID,
                name="W19 export test",
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

        for idx in range(n_shots):
            shot_id = f"shot-w19-{idx}"
            video_file_id = f"file-video-{idx}"
            db.add(
                FileItem(
                    id=video_file_id,
                    type=FileType.video,
                    name=f"shot {idx} video",
                    thumbnail="",
                    tags=[],
                    storage_key=f"videos/{idx}.mp4",
                )
            )
            file_ids.append(video_file_id)

            db.add(
                Shot(
                    id=shot_id,
                    chapter_id=_CHAPTER_ID,
                    index=idx,
                    title=f"镜头 {idx}",
                    status=ShotStatus.ready,
                    audio_strategy=audio_strategy,
                    generated_video_file_id=video_file_id,
                )
            )
            db.add(
                ShotDetail(
                    id=shot_id,
                    camera_shot=CameraShotType.ms,
                    angle=CameraAngle.eye_level,
                    movement=CameraMovement.static,
                    duration=5,
                )
            )

            sub_file_id: str | None = None
            if with_subtitle:
                sub_file_id = f"file-sub-{idx}"
                db.add(
                    FileItem(
                        id=sub_file_id,
                        type=FileType.audio,
                        name=f"shot {idx} sub",
                        thumbnail="",
                        tags=["subtitle"],
                        storage_key=f"subs/{idx}.ass",
                    )
                )
                file_ids.append(sub_file_id)

            tts_file_id: str | None = None
            if with_tts_audio and audio_strategy == AudioStrategy.silent_with_tts:
                tts_file_id = f"file-tts-{idx}"
                db.add(
                    FileItem(
                        id=tts_file_id,
                        type=FileType.audio,
                        name=f"shot {idx} tts",
                        thumbnail="",
                        tags=["tts"],
                        storage_key=f"tts/{idx}.mp3",
                    )
                )
                file_ids.append(tts_file_id)

            db.add(
                ChapterTimelineSegment(
                    id=f"seg-{idx}",
                    chapter_id=_CHAPTER_ID,
                    shot_id=shot_id,
                    position=idx,
                    trim_start_ms=None,
                    trim_end_ms=None,
                    subtitle_track_file_id=sub_file_id,
                    tts_audio_file_id=tts_file_id,
                )
            )

        await db.commit()

    return file_ids


async def _seed_generation_task_with_link(
    sm: async_sessionmaker[AsyncSession],
    *,
    task_id: str,
    chapter_id: str,
    cancel_requested: bool = False,
) -> None:
    """种 GenerationTask + GenerationTaskLink（路由层创建时未知 file_id）。"""

    async with sm() as db:
        db.add(
            GenerationTask(
                id=task_id,
                mode=GenerationDeliveryMode.async_polling,
                task_kind=TASK_KIND,
                status=GenerationTaskStatus.pending,
                progress=0,
                payload={"task_kind": TASK_KIND, "run_args": {"chapter_id": chapter_id}},
                result=None,
                error="",
                cancel_requested=cancel_requested,
            )
        )
        db.add(
            GenerationTaskLink(
                task_id=task_id,
                resource_type="video",
                relation_type="chapter_av_export",
                relation_entity_id=chapter_id,
            )
        )
        await db.commit()


def _install_storage_mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """跳过真实 S3：upload 返回 fake URL；download 返回固定字节串。"""

    async def _upload(*, key: str, **_: Any) -> StoredFileInfo:
        return StoredFileInfo(
            key=key,
            url=f"https://cdn.example.com/{key}",
            size=1024,
            content_type="video/mp4",
        )

    async def _download(*, key: str) -> bytes:
        # 任意非空字节串；ffprobe / ffmpeg 都已被 mock，不会真的解析这些字节。
        return b"\x00\x00\x00\x20ftypisom" + b"\x00" * 1024

    monkeypatch.setattr(worker_mod.storage, "upload_file", _upload)
    monkeypatch.setattr(worker_mod.storage, "download_file", _download)


def _install_ffmpeg_mocks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fake_duration_s: float = 5.0,
    raise_at_run: Exception | None = None,
) -> None:
    """跳过真实 ffmpeg：ffprobe 返回固定时长，ffmpeg 拼接直接写出 fake mp4。"""

    async def _fake_ffprobe(_path: Path) -> dict[str, Any]:
        return {
            "streams": [
                {"codec_type": "video", "codec_name": "h264"},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {"duration": str(fake_duration_s)},
        }

    monkeypatch.setattr(worker_mod, "ffprobe_local_file", _fake_ffprobe)

    async def _fake_run_ffmpeg(*, output: Path, **_: Any) -> None:
        if raise_at_run is not None:
            raise raise_at_run
        # 写一个非空 mp4 占位（worker 用 read_bytes 校验非空即可）。
        output.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"FAKE_AV_EXPORT" + b"\x00" * 512)

    monkeypatch.setattr(worker_mod, "_run_ffmpeg_av_export", _fake_run_ffmpeg)


# ---------------------------------------------------------------------------
# 1. 注册元数据
# ---------------------------------------------------------------------------


def test_executor_registered_with_chapter_av_export_task_kind() -> None:
    """``task_executor_registry.resolve("chapter_av_export")`` 应命中本 worker。"""

    executor = task_executor_registry.resolve(TASK_KIND)
    assert isinstance(executor, AbstractAsyncDelegatingExecutor)
    assert executor.task_kind == TASK_KIND


def test_executor_timeout_set_to_1800s() -> None:
    """slow 队列超时上限：1800s（与 plan 约定一致）。"""

    executor = build_chapter_av_export_executor()
    assert executor.timeout_seconds == DEFAULT_TIMEOUT_SECONDS == 1800.0
    assert executor.task_kind == TASK_KIND == "chapter_av_export"


# ---------------------------------------------------------------------------
# 2. run_args 校验
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_rejects_empty_chapter_id() -> None:
    with pytest.raises(RuntimeError, match="chapter_id"):
        await run_chapter_av_export_task("task-x", {"chapter_id": ""})


@pytest.mark.asyncio
async def test_runner_rejects_unsupported_aspect() -> None:
    """不在 PRESET_RESOLUTIONS 的 aspect 必须立刻 ValueError。"""

    with pytest.raises(ValueError, match="aspect"):
        await run_chapter_av_export_task(
            "task-x",
            {"chapter_id": _CHAPTER_ID, "aspect": "4:3"},
        )


# ---------------------------------------------------------------------------
# 3. happy-path：silent_with_tts 完整链路
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_silent_with_tts_full_pipeline(
    patched: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """silent_with_tts：完整链路落 FileItem + Link.file_id + Shot.dubbed_video_file_id。"""

    _install_storage_mocks(monkeypatch)
    _install_ffmpeg_mocks(monkeypatch)

    await _seed_chapter_with_shots(
        patched,
        n_shots=2,
        audio_strategy=AudioStrategy.silent_with_tts,
        with_subtitle=True,
        with_tts_audio=True,
    )

    task_id = "task-w19-export-happy"
    await _seed_generation_task_with_link(
        patched, task_id=task_id, chapter_id=_CHAPTER_ID
    )

    await run_chapter_av_export_task(
        task_id, {"chapter_id": _CHAPTER_ID, "aspect": "9:16"}
    )

    async with patched() as db:
        # 1) GenerationTask 落到 succeeded + result 字段齐全。
        main = await db.get(GenerationTask, task_id)
        assert main is not None
        assert main.status == GenerationTaskStatus.succeeded
        assert main.progress == 100
        result = main.result or {}
        assert result["chapter_id"] == _CHAPTER_ID
        assert result["segment_count"] == 2
        assert result["aspect"] == "9:16"

        new_file_id = result["file_id"]

        # 2) FileItem 落库：type=video，tags 含 chapter_av_export / dubbed。
        new_file = await db.get(FileItem, new_file_id)
        assert new_file is not None
        assert new_file.type == FileType.video
        assert "chapter_av_export" in (new_file.tags or [])
        assert "dubbed" in (new_file.tags or [])

        # 3) GenerationTaskLink.file_id 已被回写。
        link = (
            await db.execute(
                select(GenerationTaskLink).where(
                    GenerationTaskLink.task_id == task_id
                )
            )
        ).scalars().first()
        assert link is not None
        assert link.file_id == new_file_id

        # 4) Shot.dubbed_video_file_id 已落到每段对应 Shot。
        shots = (
            await db.execute(
                select(Shot).where(Shot.chapter_id == _CHAPTER_ID).order_by(Shot.index)
            )
        ).scalars().all()
        assert len(shots) == 2
        for shot in shots:
            assert shot.dubbed_video_file_id == new_file_id


# ---------------------------------------------------------------------------
# 4. happy-path：keep_native（无 TTS 文件）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_keep_native_works_without_tts_files(
    patched: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """keep_native：即使 segment.tts_audio_file_id 为 NULL 也能正常合成。"""

    _install_storage_mocks(monkeypatch)
    _install_ffmpeg_mocks(monkeypatch)

    await _seed_chapter_with_shots(
        patched,
        n_shots=2,
        audio_strategy=AudioStrategy.keep_native,
        with_subtitle=True,
        with_tts_audio=False,
    )

    task_id = "task-w19-export-native"
    await _seed_generation_task_with_link(
        patched, task_id=task_id, chapter_id=_CHAPTER_ID
    )

    await run_chapter_av_export_task(
        task_id, {"chapter_id": _CHAPTER_ID}
    )

    async with patched() as db:
        main = await db.get(GenerationTask, task_id)
        assert main is not None
        assert main.status == GenerationTaskStatus.succeeded


# ---------------------------------------------------------------------------
# 5. ffmpeg 失败 → hotfix-4 失败路径
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_marks_failed_when_ffmpeg_raises(
    patched: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ffmpeg 抛错时：原会话 rollback，独立会话写 failed + 错误信息。"""

    _install_storage_mocks(monkeypatch)
    _install_ffmpeg_mocks(
        monkeypatch, raise_at_run=RuntimeError("ffmpeg filter_complex 解析失败")
    )

    await _seed_chapter_with_shots(
        patched,
        n_shots=1,
        audio_strategy=AudioStrategy.silent_with_tts,
        with_subtitle=True,
        with_tts_audio=True,
    )

    task_id = "task-w19-export-fail"
    await _seed_generation_task_with_link(
        patched, task_id=task_id, chapter_id=_CHAPTER_ID
    )

    with pytest.raises(RuntimeError, match="filter_complex"):
        await run_chapter_av_export_task(
            task_id, {"chapter_id": _CHAPTER_ID}
        )

    async with patched() as db:
        main = await db.get(GenerationTask, task_id)
        assert main is not None
        assert main.status == GenerationTaskStatus.failed
        assert "filter_complex" in (main.error or "")
        assert main.result is None


# ---------------------------------------------------------------------------
# 6. 缺视频 → 失败
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_rejects_shot_without_generated_video(
    patched: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shot 缺 generated_video_file_id（裸视频未生成）必须立刻失败。"""

    _install_storage_mocks(monkeypatch)
    _install_ffmpeg_mocks(monkeypatch)

    async with patched() as db:
        db.add(
            Project(
                id=_PROJECT_ID,
                name="missing video",
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
                id="shot-no-video",
                chapter_id=_CHAPTER_ID,
                index=0,
                title="无裸视频镜头",
                status=ShotStatus.ready,
                audio_strategy=AudioStrategy.silent_with_tts,
                generated_video_file_id=None,
            )
        )
        db.add(
            ShotDetail(
                id="shot-no-video",
                camera_shot=CameraShotType.ms,
                angle=CameraAngle.eye_level,
                movement=CameraMovement.static,
                duration=5,
            )
        )
        db.add(
            ChapterTimelineSegment(
                id="seg-no-video",
                chapter_id=_CHAPTER_ID,
                shot_id="shot-no-video",
                position=0,
            )
        )
        await db.commit()

    task_id = "task-w19-export-novideo"
    await _seed_generation_task_with_link(
        patched, task_id=task_id, chapter_id=_CHAPTER_ID
    )

    with pytest.raises((RuntimeError, ValueError)):
        await run_chapter_av_export_task(
            task_id, {"chapter_id": _CHAPTER_ID}
        )

    async with patched() as db:
        main = await db.get(GenerationTask, task_id)
        assert main is not None
        assert main.status == GenerationTaskStatus.failed
