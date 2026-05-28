"""W31-T2 chapter_timeline schemas + ChapterAvExportRequest 契约 round-trip 测试。

覆盖目标：
    1. ``ChapterTimelineSegmentWrite`` 接受 BGM/SFX/ducking 三字段；
       ducking 默认 -12.0；范围 [-30.0, 0.0] 之外 → ``ValidationError``。
    2. ``ChapterTimelineSegmentRead`` 同样含 BGM/SFX/ducking 三字段，
       round-trip 序列化值保持。
    3. ``ChapterAvExportRequest`` 接受 ``audio_mix_mode`` 字段，缺省
       ``voice_only``，可写入 ``voice_bgm`` / ``full`` / ``off``。
"""

# pylint: disable=invalid-name

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.commerce.tasks import ChapterAvExportRequest
from app.schemas.studio.chapter_timeline import (
    ChapterTimelineSegmentRead,
    ChapterTimelineSegmentWrite,
    TimelineClipStatus,
)


# ---------------------------------------------------------------------------
# ChapterTimelineSegmentWrite — BGM / SFX / ducking
# ---------------------------------------------------------------------------


def test_segment_write_defaults_bgm_sfx_to_none_and_ducking_to_minus_12() -> None:
    """缺省时 BGM/SFX 为 None，ducking_db 为 -12.0（W19 行为不变 + W31 默认）。"""

    payload = ChapterTimelineSegmentWrite(shot_id="shot-1")
    assert payload.bgm_file_id is None
    assert payload.sfx_file_id is None
    assert payload.bgm_ducking_db == pytest.approx(-12.0)


def test_segment_write_round_trips_bgm_sfx_ducking() -> None:
    """显式写入 BGM/SFX/ducking 三字段，模型反序列化保持原值。"""

    payload = ChapterTimelineSegmentWrite(
        shot_id="shot-1",
        bgm_file_id="bgm-99",
        sfx_file_id="sfx-99",
        bgm_ducking_db=-18.5,
    )
    dumped = payload.model_dump()
    assert dumped["bgm_file_id"] == "bgm-99"
    assert dumped["sfx_file_id"] == "sfx-99"
    assert dumped["bgm_ducking_db"] == pytest.approx(-18.5)


def test_segment_write_rejects_ducking_below_minus_30() -> None:
    """``bgm_ducking_db`` < -30.0 触发 422。"""

    with pytest.raises(ValidationError):
        ChapterTimelineSegmentWrite(shot_id="shot-1", bgm_ducking_db=-40.0)


def test_segment_write_rejects_ducking_above_zero() -> None:
    """``bgm_ducking_db`` > 0.0 触发 422（语义上正增益没意义）。"""

    with pytest.raises(ValidationError):
        ChapterTimelineSegmentWrite(shot_id="shot-1", bgm_ducking_db=3.0)


# ---------------------------------------------------------------------------
# ChapterTimelineSegmentRead — BGM / SFX / ducking 透传
# ---------------------------------------------------------------------------


def test_segment_read_includes_bgm_sfx_ducking_fields() -> None:
    """Read 模型显式持有 BGM/SFX/ducking 三字段（前端 props 用）。"""

    read = ChapterTimelineSegmentRead(
        id="seg-1",
        shot_id="shot-1",
        position=0,
        clip_status=TimelineClipStatus.ready,
        bgm_file_id="bgm-1",
        sfx_file_id="sfx-1",
        bgm_ducking_db=-15.0,
    )
    assert read.bgm_file_id == "bgm-1"
    assert read.sfx_file_id == "sfx-1"
    assert read.bgm_ducking_db == pytest.approx(-15.0)


# ---------------------------------------------------------------------------
# ChapterAvExportRequest — audio_mix_mode
# ---------------------------------------------------------------------------


def test_chapter_av_export_request_defaults_audio_mix_mode_to_voice_only() -> None:
    """缺省值为 ``voice_only``（与 W19 默认值兼容，不破坏既有调用方）。"""

    body = ChapterAvExportRequest(chapter_id="chap-1")
    assert body.audio_mix_mode == "voice_only"


@pytest.mark.parametrize(
    "mode", ["off", "voice_only", "voice_bgm", "full"]
)
def test_chapter_av_export_request_accepts_all_audio_mix_modes(mode: str) -> None:
    """4 个合法 ``AudioMixMode`` 取值均可序列化。"""

    body = ChapterAvExportRequest(chapter_id="chap-1", audio_mix_mode=mode)
    assert body.audio_mix_mode == mode


def test_chapter_av_export_request_rejects_unknown_field() -> None:
    """``extra="forbid"`` 仍生效：未知字段 422。"""

    with pytest.raises(ValidationError):
        ChapterAvExportRequest(
            chapter_id="chap-1",
            audio_mix_mode="voice_only",
            unknown_field="x",  # type: ignore[call-arg]
        )
