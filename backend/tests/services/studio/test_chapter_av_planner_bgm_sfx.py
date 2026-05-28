"""W31-T4 chapter_av_export_task BGM/SFX 加载与 audio_mix_mode 路由测试。

覆盖目标：
1. ``_coerce_audio_mix_mode`` 正确把字符串映射为 ``AudioMixMode``，未知值
   fallback voice_only + warning。
2. ``_safe_load_optional_file`` 缺 file_id / file 行 / storage_key 时返回
   None 而非 raise（W31 fallback 设计）。
3. ``_resolve_segment_resources`` 返回 7 元组，BGM/SFX 缺失时为 None。
4. ``_build_filter_specs`` 在 voice_bgm 模式下下载 BGM 并把 input_index 写
   入 SegmentFilterSpec；在 voice_only 模式下完全不下载 BGM/SFX。
5. ``_build_filter_specs`` 在 full 模式下下载 BGM + SFX 并都把 input_index
   传给 SegmentFilterSpec。
6. ``run_chapter_av_export_task`` 把 ``audio_mix_mode`` 写到结果 dict。
"""

# pylint: disable=redefined-outer-name,invalid-name,duplicate-code,too-many-arguments,too-many-locals,too-many-statements

from __future__ import annotations

import asyncio
import logging
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
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
from app.models.types import AudioMixMode, AudioStrategy
from app.services.studio import chapter_av_export_task as worker_mod
from app.services.studio.chapter_av_export_task import (
    _build_filter_specs,
    _coerce_audio_mix_mode,
    _resolve_segment_resources,
    _safe_load_optional_file,
    run_chapter_av_export_task,
)


_PROJECT_ID = "proj-w31"
_CHAPTER_ID = "chap-w31"


# ---------------------------------------------------------------------------
# 1. _coerce_audio_mix_mode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("voice_only", AudioMixMode.voice_only),
        ("voice_bgm", AudioMixMode.voice_bgm),
        ("full", AudioMixMode.full),
        ("off", AudioMixMode.off),
    ],
)
def test_coerce_audio_mix_mode_maps_known_values(
    raw: str, expected: AudioMixMode
) -> None:
    """4 个合法 mode 字符串均能映射到对应枚举。"""

    assert _coerce_audio_mix_mode(raw) == expected


def test_coerce_audio_mix_mode_falls_back_on_unknown_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """未知值 fallback voice_only 并写 warning（不 raise）。"""

    caplog.set_level(logging.WARNING)
    assert _coerce_audio_mix_mode("garbage") == AudioMixMode.voice_only
    assert any("未知 audio_mix_mode" in rec.message for rec in caplog.records)


def test_coerce_audio_mix_mode_falls_back_on_empty_value() -> None:
    """空 / None / 空白字符串走默认 voice_only。"""

    assert _coerce_audio_mix_mode(None) == AudioMixMode.voice_only
    assert _coerce_audio_mix_mode("") == AudioMixMode.voice_only
    assert _coerce_audio_mix_mode("  ") == AudioMixMode.voice_only


# ---------------------------------------------------------------------------
# 2 / 3 / 4 / 5：DB-level helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def session_local(tmp_path: Path) -> Generator[async_sessionmaker[AsyncSession], None, None]:
    """临时 SQLite + Base.metadata.create_all。"""

    db_path = tmp_path / "av-export-w31.db"
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


async def _seed_chapter_with_segments(
    sm: async_sessionmaker[AsyncSession],
    *,
    n_shots: int = 1,
    bgm_files_per_shot: bool = False,
    sfx_files_per_shot: bool = False,
    bgm_ducking_db: float = -12.0,
    sfx_offset_ms: int = 0,
) -> dict[str, str | None]:
    """种入 Project + Chapter + N 个 Shot + ChapterTimelineSegment（可选 BGM/SFX）。

    Args:
        sm: 异步 session_maker。
        n_shots: 镜头数。
        bgm_files_per_shot / sfx_files_per_shot: 是否给每段建 BGM/SFX FileItem。
        bgm_ducking_db: 写入 segment 的 ducking 增益。
        sfx_offset_ms: 写入 segment 的 SFX 偏移（W31-followup 新增），缺省
            0 等价 W31 既有行为；测试 SFX 时间轴时调到非 0 值。

    Returns:
        ``{shot_id -> bgm_file_id_or_None, sfx_<shot_id> -> sfx_file_id_or_None}``。
    """

    out: dict[str, str | None] = {}
    async with sm() as db:
        db.add(
            Project(
                id=_PROJECT_ID,
                name="W31",
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
            shot_id = f"shot-{idx}"
            video_file_id = f"file-video-{idx}"
            db.add(
                FileItem(
                    id=video_file_id,
                    type=FileType.video,
                    name=f"video {idx}",
                    storage_key=f"videos/{idx}.mp4",
                )
            )
            db.add(
                Shot(
                    id=shot_id,
                    chapter_id=_CHAPTER_ID,
                    index=idx,
                    title=f"镜头 {idx}",
                    status=ShotStatus.ready,
                    audio_strategy=AudioStrategy.keep_native,
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

            bgm_id: str | None = None
            if bgm_files_per_shot:
                bgm_id = f"file-bgm-{idx}"
                db.add(
                    FileItem(
                        id=bgm_id,
                        type=FileType.audio,
                        name=f"bgm {idx}",
                        storage_key=f"bgm/{idx}.mp3",
                    )
                )
            sfx_id: str | None = None
            if sfx_files_per_shot:
                sfx_id = f"file-sfx-{idx}"
                db.add(
                    FileItem(
                        id=sfx_id,
                        type=FileType.audio,
                        name=f"sfx {idx}",
                        storage_key=f"sfx/{idx}.mp3",
                    )
                )

            db.add(
                ChapterTimelineSegment(
                    id=f"seg-{idx}",
                    chapter_id=_CHAPTER_ID,
                    shot_id=shot_id,
                    position=idx,
                    bgm_file_id=bgm_id,
                    sfx_file_id=sfx_id,
                    bgm_ducking_db=bgm_ducking_db,
                    sfx_offset_ms=sfx_offset_ms,
                )
            )
            out[shot_id] = bgm_id
            out[f"sfx_{shot_id}"] = sfx_id
        await db.commit()
    return out


def test_safe_load_optional_file_returns_none_for_missing_id(
    session_local: async_sessionmaker[AsyncSession],
) -> None:
    """``file_id`` 为 None / 空字符串 → 返回 None，不查 DB。"""

    async def _go() -> None:
        async with session_local() as db:
            assert await _safe_load_optional_file(db, file_id=None, label="x") is None
            assert await _safe_load_optional_file(db, file_id="", label="x") is None

    asyncio.run(_go())


def test_safe_load_optional_file_returns_none_on_dangling_id(
    session_local: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """file_id 引用了不存在的行 → 返回 None + warning。"""

    caplog.set_level(logging.WARNING)

    async def _go() -> None:
        async with session_local() as db:
            res = await _safe_load_optional_file(
                db, file_id="ghost", label="BGM 缺失"
            )
            assert res is None

    asyncio.run(_go())
    assert any("不存在" in rec.message for rec in caplog.records)


def test_resolve_segment_resources_returns_seven_tuple_with_bgm_sfx_none(
    session_local: async_sessionmaker[AsyncSession],
) -> None:
    """voice_only-only 数据：BGM/SFX 行未写 → 返回 7 元组，最后两项 None。"""

    asyncio.run(_seed_chapter_with_segments(session_local))

    async def _go() -> None:
        async with session_local() as db:
            rows = await _resolve_segment_resources(db, chapter_id=_CHAPTER_ID)
            assert len(rows) == 1
            tup = rows[0]
            assert len(tup) == 7
            seg, _shot, _video, _ass, _tts, bgm, sfx = tup
            assert bgm is None
            assert sfx is None
            assert seg.bgm_ducking_db == pytest.approx(-12.0)

    asyncio.run(_go())


def test_resolve_segment_resources_loads_bgm_and_sfx_filerow(
    session_local: async_sessionmaker[AsyncSession],
) -> None:
    """填了 BGM/SFX file_id 时 7 元组的最后两项是 FileItem 实例。"""

    asyncio.run(
        _seed_chapter_with_segments(
            session_local, bgm_files_per_shot=True, sfx_files_per_shot=True
        )
    )

    async def _go() -> None:
        async with session_local() as db:
            rows = await _resolve_segment_resources(db, chapter_id=_CHAPTER_ID)
            seg, _shot, _video, _ass, _tts, bgm, sfx = rows[0]
            assert bgm is not None and bgm.id == "file-bgm-0"
            assert sfx is not None and sfx.id == "file-sfx-0"

    asyncio.run(_go())


def test_build_filter_specs_voice_only_skips_bgm_sfx_download(
    session_local: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """voice_only 模式即使 segment 带 BGM/SFX 也不下载（节省 IO）。"""

    asyncio.run(
        _seed_chapter_with_segments(
            session_local, bgm_files_per_shot=True, sfx_files_per_shot=True
        )
    )

    download_keys: list[str] = []

    async def _fake_download(*, key: str) -> bytes:
        download_keys.append(key)
        return b"\x00\x00"

    async def _fake_probe(_p: Path) -> dict[str, Any]:
        return {"format": {"duration": "5.0"}, "streams": []}

    def _fake_probe_dur(_probe: dict[str, Any]) -> tuple[float, bool]:
        return 5.0, False

    monkeypatch.setattr(worker_mod.storage, "download_file", _fake_download)
    monkeypatch.setattr(worker_mod, "ffprobe_local_file", _fake_probe)
    monkeypatch.setattr(worker_mod, "probe_duration_and_audio", _fake_probe_dur)

    async def _go() -> None:
        async with session_local() as db:
            rows = await _resolve_segment_resources(db, chapter_id=_CHAPTER_ID)
            specs, inputs, _ass = await _build_filter_specs(
                seg_resources=rows,
                tmp_path=tmp_path,
                audio_strategy_override=None,
                audio_mix_mode=AudioMixMode.voice_only,
            )
        assert specs[0].audio_mix_mode == AudioMixMode.voice_only
        assert specs[0].bgm_input_index is None
        assert specs[0].sfx_input_index is None
        # 只下载视频，没有 BGM/SFX
        assert any("videos/" in k for k in download_keys)
        assert not any("bgm/" in k for k in download_keys)
        assert not any("sfx/" in k for k in download_keys)
        assert len(inputs) == 1  # 只 1 个视频

    asyncio.run(_go())


def test_build_filter_specs_voice_bgm_downloads_bgm_only(
    session_local: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """voice_bgm 模式下载 BGM，跳过 SFX。"""

    asyncio.run(
        _seed_chapter_with_segments(
            session_local, bgm_files_per_shot=True, sfx_files_per_shot=True
        )
    )

    download_keys: list[str] = []

    async def _fake_download(*, key: str) -> bytes:
        download_keys.append(key)
        return b"\x00"

    async def _fake_probe(_p: Path) -> dict[str, Any]:
        return {"format": {"duration": "5.0"}, "streams": []}

    def _fake_probe_dur(_probe: dict[str, Any]) -> tuple[float, bool]:
        return 5.0, False

    monkeypatch.setattr(worker_mod.storage, "download_file", _fake_download)
    monkeypatch.setattr(worker_mod, "ffprobe_local_file", _fake_probe)
    monkeypatch.setattr(worker_mod, "probe_duration_and_audio", _fake_probe_dur)

    async def _go() -> None:
        async with session_local() as db:
            rows = await _resolve_segment_resources(db, chapter_id=_CHAPTER_ID)
            specs, _inputs, _ass = await _build_filter_specs(
                seg_resources=rows,
                tmp_path=tmp_path,
                audio_strategy_override=None,
                audio_mix_mode=AudioMixMode.voice_bgm,
            )
        assert specs[0].audio_mix_mode == AudioMixMode.voice_bgm
        assert specs[0].bgm_input_index is not None
        assert specs[0].sfx_input_index is None  # voice_bgm 不拉 SFX
        assert any("bgm/" in k for k in download_keys)
        assert not any("sfx/" in k for k in download_keys)

    asyncio.run(_go())


def test_build_filter_specs_full_downloads_bgm_and_sfx(
    session_local: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """full 模式下载 BGM + SFX，input_index 都写入 spec。"""

    asyncio.run(
        _seed_chapter_with_segments(
            session_local,
            bgm_files_per_shot=True,
            sfx_files_per_shot=True,
            bgm_ducking_db=-18.0,
        )
    )

    async def _fake_download(*, key: str) -> bytes:
        del key
        return b"\x00"

    async def _fake_probe(_p: Path) -> dict[str, Any]:
        return {"format": {"duration": "5.0"}, "streams": []}

    def _fake_probe_dur(_probe: dict[str, Any]) -> tuple[float, bool]:
        return 5.0, False

    monkeypatch.setattr(worker_mod.storage, "download_file", _fake_download)
    monkeypatch.setattr(worker_mod, "ffprobe_local_file", _fake_probe)
    monkeypatch.setattr(worker_mod, "probe_duration_and_audio", _fake_probe_dur)

    async def _go() -> None:
        async with session_local() as db:
            rows = await _resolve_segment_resources(db, chapter_id=_CHAPTER_ID)
            specs, _inputs, _ass = await _build_filter_specs(
                seg_resources=rows,
                tmp_path=tmp_path,
                audio_strategy_override=None,
                audio_mix_mode=AudioMixMode.full,
            )
        s = specs[0]
        assert s.audio_mix_mode == AudioMixMode.full
        assert s.bgm_input_index is not None
        assert s.sfx_input_index is not None
        assert s.sfx_input_index > s.bgm_input_index  # SFX 在 BGM 之后
        assert s.bgm_ducking_db == pytest.approx(-18.0)

    asyncio.run(_go())


# ---------------------------------------------------------------------------
# W31-followup #6: sfx_offset_ms 真实值透传 + adelay 用真实 offset
# ---------------------------------------------------------------------------


def test_build_filter_specs_passes_real_sfx_offset_ms(
    session_local: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """W31-followup #6：planner 必须把 ``seg.sfx_offset_ms`` 真实值透传到 spec。

    历史 W31 在 ``_build_filter_specs`` 把 ``sfx_offset_ms`` 写死成 0，导致
    DB 列加了也用不上。本测试 seed 一个 segment 把 sfx_offset_ms=2500，
    断言 spec 拿到的是 2500 而非 0。
    """
    asyncio.run(
        _seed_chapter_with_segments(
            session_local,
            bgm_files_per_shot=True,
            sfx_files_per_shot=True,
            sfx_offset_ms=2500,
        )
    )

    async def _fake_download(*, key: str) -> bytes:
        del key
        return b"\x00"

    async def _fake_probe(_p: Path) -> dict[str, Any]:
        return {"format": {"duration": "5.0"}, "streams": []}

    def _fake_probe_dur(_probe: dict[str, Any]) -> tuple[float, bool]:
        return 5.0, False

    monkeypatch.setattr(worker_mod.storage, "download_file", _fake_download)
    monkeypatch.setattr(worker_mod, "ffprobe_local_file", _fake_probe)
    monkeypatch.setattr(worker_mod, "probe_duration_and_audio", _fake_probe_dur)

    async def _go() -> None:
        async with session_local() as db:
            rows = await _resolve_segment_resources(db, chapter_id=_CHAPTER_ID)
            specs, _inputs, _ass = await _build_filter_specs(
                seg_resources=rows,
                tmp_path=tmp_path,
                audio_strategy_override=None,
                audio_mix_mode=AudioMixMode.full,
            )
        assert specs[0].sfx_offset_ms == 2500, (
            "planner 必须把 seg.sfx_offset_ms 真实值透传到 SegmentFilterSpec"
        )

    asyncio.run(_go())


def test_full_mode_filter_uses_real_sfx_offset_in_adelay(
    session_local: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """W31-followup #6：``full`` 模式 ffmpeg adelay 必须用真实 offset 而非 0。

    串联 planner + filter：seed sfx_offset_ms=1800 → 调 ``_build_filter_specs``
    + ``build_segment_filter`` → 断言 filter 字符串里有 ``adelay=1800|1800``，
    不是 ``adelay=0|0``（W31 写死时的退化路径）。
    """
    from app.services.studio.chapter_av_export_filter import (
        build_segment_filter,
    )

    asyncio.run(
        _seed_chapter_with_segments(
            session_local,
            bgm_files_per_shot=True,
            sfx_files_per_shot=True,
            sfx_offset_ms=1800,
        )
    )

    async def _fake_download(*, key: str) -> bytes:
        del key
        return b"\x00"

    async def _fake_probe(_p: Path) -> dict[str, Any]:
        return {"format": {"duration": "5.0"}, "streams": []}

    def _fake_probe_dur(_probe: dict[str, Any]) -> tuple[float, bool]:
        return 5.0, False

    monkeypatch.setattr(worker_mod.storage, "download_file", _fake_download)
    monkeypatch.setattr(worker_mod, "ffprobe_local_file", _fake_probe)
    monkeypatch.setattr(worker_mod, "probe_duration_and_audio", _fake_probe_dur)

    async def _go() -> str:
        async with session_local() as db:
            rows = await _resolve_segment_resources(db, chapter_id=_CHAPTER_ID)
            specs, _inputs, _ass = await _build_filter_specs(
                seg_resources=rows,
                tmp_path=tmp_path,
                audio_strategy_override=None,
                audio_mix_mode=AudioMixMode.full,
            )
        return build_segment_filter(specs[0], width=1080, height=1920)

    chain = asyncio.run(_go())
    assert "adelay=1800|1800" in chain, (
        f"filter graph 必须用真实 sfx_offset，得到: {chain[:200]}"
    )
    assert "adelay=0|0" not in chain, (
        "filter graph 不能再出现写死 adelay=0|0 的退化路径"
    )


def test_runner_records_audio_mix_mode_in_result(
    session_local: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """完整 happy path：result dict 含 ``audio_mix_mode`` 字段。"""

    asyncio.run(_seed_chapter_with_segments(session_local))

    async def _no_cancel(*_a: Any, **_k: Any) -> bool:
        return False

    async def _fake_download(*, key: str) -> bytes:
        del key
        return b"\x00\x00"

    async def _fake_probe(_p: Path) -> dict[str, Any]:
        return {"format": {"duration": "5.0"}, "streams": []}

    def _fake_probe_dur(_probe: dict[str, Any]) -> tuple[float, bool]:
        return 5.0, False

    async def _fake_run_ffmpeg(**kwargs: Any) -> None:
        kwargs["output"].write_bytes(b"\x00\x01\x02")

    async def _fake_upload(**_kwargs: Any) -> StoredFileInfo:
        return StoredFileInfo(
            url="https://test/master.mp4", key=_kwargs.get("key", "x")
        )

    monkeypatch.setattr(worker_mod, "async_session_maker", session_local)
    monkeypatch.setattr(worker_mod, "cancel_if_requested_async", _no_cancel)
    monkeypatch.setattr(worker_mod.storage, "download_file", _fake_download)
    monkeypatch.setattr(worker_mod.storage, "upload_file", _fake_upload)
    monkeypatch.setattr(worker_mod, "ffprobe_local_file", _fake_probe)
    monkeypatch.setattr(worker_mod, "probe_duration_and_audio", _fake_probe_dur)
    monkeypatch.setattr(worker_mod, "_run_ffmpeg_av_export", _fake_run_ffmpeg)

    async def _seed_task() -> str:
        async with session_local() as db:
            task = GenerationTask(
                id="task-w31",
                mode=GenerationDeliveryMode.async_polling,
                task_kind="chapter_av_export",
                status=GenerationTaskStatus.pending,
                progress=0,
            )
            db.add(task)
            db.add(
                GenerationTaskLink(
                    task_id="task-w31",
                    relation_type="chapter_av_export",
                    relation_entity_id=_CHAPTER_ID,
                    resource_type="video",
                )
            )
            await db.commit()
            return task.id

    task_id = asyncio.run(_seed_task())

    asyncio.run(
        run_chapter_av_export_task(
            task_id,
            {"chapter_id": _CHAPTER_ID, "audio_mix_mode": "voice_only"},
        )
    )

    async def _check() -> None:
        async with session_local() as db:
            task = await db.get(GenerationTask, task_id)
            assert task is not None
            assert task.status == GenerationTaskStatus.succeeded
            result = task.result
            assert result is not None
            assert result.get("audio_mix_mode") == "voice_only"

    asyncio.run(_check())
