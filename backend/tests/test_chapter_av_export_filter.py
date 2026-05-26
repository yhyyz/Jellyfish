"""``chapter_av_export_filter`` 纯函数单元测试（P3 W19 T19-4 / T19-5）。

覆盖目标：
1. ``escape_subtitle_path`` 6 类特殊字符转义；
2. ``escape_subtitle_path`` Windows 反斜杠归一化为正斜杠；
3. ``build_segment_filter`` keep_native 路径产出原音 atrim 链；
4. ``build_segment_filter`` silent_with_tts 单 TTS 路径走 anull 直通跳过 amix；
5. ``build_segment_filter`` silent_with_tts 多 TTS 走 amix=normalize=0；
6. ``build_segment_filter`` silent_with_tts 空 TTS 路径降级 anullsrc 静音；
7. ``build_segment_filter`` 视频归一化四件套（setsar / fps / format / scale+pad）齐全；
8. ``build_segment_filter`` 字幕缺失时跳过 subtitles= 滤镜；
9. ``build_filter_complex`` concat 拼接 + loudnorm 收尾；
10. ``build_filter_complex`` 空 specs / index 不连续 → ValueError；
11. ``build_filter_complex`` aspect=16:9 走 1280×720。
"""

# pylint: disable=redefined-outer-name

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.types import AudioStrategy
from app.services.studio.chapter_av_export_filter import (
    LOUDNORM_I,
    PRESET_RESOLUTIONS,
    SegmentFilterSpec,
    TtsClipSpec,
    build_filter_complex,
    build_segment_filter,
    escape_subtitle_path,
)


# ---------------------------------------------------------------------------
# 1. escape_subtitle_path
# ---------------------------------------------------------------------------


def test_escape_subtitle_path_handles_all_six_special_chars() -> None:
    """6 类特殊字符（``\\`` / ``:`` / ``'`` / ``,`` / ``[`` / ``]``）均被转义。"""

    raw = "/tmp/dir/sub:01,01[a]'.ass"
    escaped = escape_subtitle_path(raw)
    assert "\\:" in escaped
    assert "\\," in escaped
    assert "\\[" in escaped
    assert "\\]" in escaped
    assert "\\'" in escaped


def test_escape_subtitle_path_normalizes_windows_backslash() -> None:
    """Windows 反斜杠先归一化为正斜杠，再做 ffmpeg 转义。"""

    raw = "C:\\Users\\me\\sub.ass"
    escaped = escape_subtitle_path(raw)
    # 反斜杠应已被替换为正斜杠（不出现裸 ``\``，但出现 ``\\:`` 是 ``:`` 转义产物）。
    assert "C\\:/Users/me/sub.ass" == escaped


def test_escape_subtitle_path_accepts_pathlike() -> None:
    """``Path`` 对象与字符串行为一致。"""

    p = Path("/tmp/x:y.ass")
    assert escape_subtitle_path(p) == escape_subtitle_path("/tmp/x:y.ass")


# ---------------------------------------------------------------------------
# 2. build_segment_filter — keep_native 路径
# ---------------------------------------------------------------------------


def _spec_keep_native(idx: int = 0) -> SegmentFilterSpec:
    return SegmentFilterSpec(
        index=idx,
        video_input_index=idx,
        trim_start_s=0.0,
        trim_end_s=5.0,
        duration_s=5.0,
        audio_strategy=AudioStrategy.keep_native,
        ass_path=Path("/tmp/sub_0.ass"),
    )


def test_segment_filter_keep_native_uses_video_input_audio() -> None:
    """keep_native 段从 [v_idx:a] 取原音轨 + atrim。"""

    chain = build_segment_filter(_spec_keep_native(idx=0), width=1080, height=1920)
    assert "[0:a]atrim=start=0.0:end=5.0" in chain
    assert "asetpts=PTS-STARTPTS" in chain
    assert "[a0]" in chain
    # keep_native 路径绝不应出现 amix（无 TTS 混合）。
    assert "amix=" not in chain


# ---------------------------------------------------------------------------
# 3. build_segment_filter — silent_with_tts 路径
# ---------------------------------------------------------------------------


def _spec_silent(
    idx: int = 0,
    tts_count: int = 1,
    base_input_idx: int = 0,
) -> SegmentFilterSpec:
    """构造 silent_with_tts spec；TTS input_index 顺序累加。"""

    tts_clips = tuple(
        TtsClipSpec(input_index=base_input_idx + 1 + j, offset_ms=j * 1000)
        for j in range(tts_count)
    )
    return SegmentFilterSpec(
        index=idx,
        video_input_index=base_input_idx,
        trim_start_s=0.0,
        trim_end_s=5.0,
        duration_s=5.0,
        audio_strategy=AudioStrategy.silent_with_tts,
        ass_path=Path("/tmp/sub.ass"),
        tts_clips=tts_clips,
    )


def test_segment_filter_silent_single_tts_skips_amix() -> None:
    """单段 TTS 走 anull 直通，不进 amix（性能优化）。"""

    chain = build_segment_filter(_spec_silent(tts_count=1), width=1080, height=1920)
    assert "amix=" not in chain
    assert "anull[a0_mix]" in chain
    assert "[1:a]adelay=0|0[a0_t0]" in chain


def test_segment_filter_silent_multi_tts_uses_amix_normalize_zero() -> None:
    """多段 TTS 走 amix=...:normalize=0:dropout_transition=0（关键参数）。"""

    chain = build_segment_filter(_spec_silent(tts_count=3), width=1080, height=1920)
    assert "amix=inputs=3" in chain
    assert "normalize=0" in chain
    assert "dropout_transition=0" in chain
    assert "duration=longest" in chain


def test_segment_filter_silent_zero_tts_falls_back_to_anullsrc() -> None:
    """无 TTS 段（silent_with_tts 但 tts_clips 为空）兜底纯静音轨。"""

    spec = SegmentFilterSpec(
        index=0,
        video_input_index=0,
        trim_start_s=0.0,
        trim_end_s=4.0,
        duration_s=4.0,
        audio_strategy=AudioStrategy.silent_with_tts,
        tts_clips=(),
    )
    chain = build_segment_filter(spec, width=1080, height=1920)
    assert "anullsrc=" in chain
    # anullsrc 兜底路径不调 amix。
    assert "amix=" not in chain


def test_segment_filter_silent_tts_aligns_to_segment_duration() -> None:
    """TTS 路径必须 apad+atrim=duration=segment_duration 对齐到视频时长。"""

    chain = build_segment_filter(_spec_silent(tts_count=2), width=1080, height=1920)
    assert "apad,atrim=duration=5.0" in chain


def test_segment_filter_silent_tts_offset_emits_adelay() -> None:
    """TTS 段在 segment 内偏移通过 adelay=ms|ms 双声道写两次。"""

    spec = SegmentFilterSpec(
        index=0,
        video_input_index=0,
        trim_start_s=0.0,
        trim_end_s=5.0,
        duration_s=5.0,
        audio_strategy=AudioStrategy.silent_with_tts,
        tts_clips=(
            TtsClipSpec(input_index=1, offset_ms=0),
            TtsClipSpec(input_index=2, offset_ms=2500),
        ),
    )
    chain = build_segment_filter(spec, width=1080, height=1920)
    assert "[1:a]adelay=0|0" in chain
    assert "[2:a]adelay=2500|2500" in chain


# ---------------------------------------------------------------------------
# 4. build_segment_filter — 视频归一化四件套
# ---------------------------------------------------------------------------


def test_segment_filter_video_normalization_four_filters_present() -> None:
    """concat filter 强制各段视频参数一致——四件套缺一不可：
    setsar=1, fps=N, format=yuv420p, scale+pad。
    """

    chain = build_segment_filter(_spec_keep_native(), width=1080, height=1920, fps=30)
    assert "setsar=1" in chain
    assert "fps=30" in chain
    assert "format=yuv420p" in chain
    assert "scale=1080:1920:force_original_aspect_ratio=decrease" in chain
    assert "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black" in chain


def test_segment_filter_skips_subtitles_when_ass_path_none() -> None:
    """无字幕段 (ass_path=None) 直接跳过 subtitles= 滤镜。"""

    spec = SegmentFilterSpec(
        index=0,
        video_input_index=0,
        trim_start_s=0.0,
        trim_end_s=5.0,
        duration_s=5.0,
        audio_strategy=AudioStrategy.keep_native,
        ass_path=None,
    )
    chain = build_segment_filter(spec, width=1080, height=1920)
    assert "subtitles=" not in chain


def test_segment_filter_includes_subtitles_with_filename_form() -> None:
    """有 ass_path 时用 ``subtitles=filename='...'`` 形式（非 raw 路径）。"""

    chain = build_segment_filter(_spec_keep_native(), width=1080, height=1920)
    assert "subtitles=filename='" in chain
    assert "/tmp/sub_0.ass" in chain


# ---------------------------------------------------------------------------
# 5. build_filter_complex — concat 拼接 + loudnorm 收尾
# ---------------------------------------------------------------------------


def test_build_filter_complex_concat_v1a1_with_correct_count() -> None:
    """N 段产出 ``concat=n=N:v=1:a=1[vc][ac]``。"""

    specs = [
        _spec_keep_native(idx=0),
        _spec_silent(idx=1, tts_count=1, base_input_idx=1),
    ]
    fc = build_filter_complex(specs, aspect="9:16")
    assert "[v0][a0][v1][a1]concat=n=2:v=1:a=1[vc][ac]" in fc


def test_build_filter_complex_loudnorm_uses_default_targets() -> None:
    """默认 loudnorm 参数：I=-16 / TP=-1.5 / LRA=11，含 print_format=summary。"""

    specs = [_spec_keep_native()]
    fc = build_filter_complex(specs)
    assert f"loudnorm=I={LOUDNORM_I}:TP=-1.5:LRA=11" in fc
    assert "print_format=summary[aout]" in fc


def test_build_filter_complex_youtube_target_lufs_minus_14() -> None:
    """YouTube/TikTok 风格：lufs_target=-14。"""

    specs = [_spec_keep_native()]
    fc = build_filter_complex(specs, lufs_target=-14)
    assert "loudnorm=I=-14:" in fc


# ---------------------------------------------------------------------------
# 6. 错误路径
# ---------------------------------------------------------------------------


def test_build_filter_complex_empty_specs_raises() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        build_filter_complex([])


def test_build_filter_complex_index_not_contiguous_raises() -> None:
    """specs[i].index 必须严格等于 i，跳号 → ValueError。"""

    specs = [_spec_keep_native(idx=0), _spec_keep_native(idx=2)]
    with pytest.raises(ValueError, match="index"):
        build_filter_complex(specs)


def test_build_filter_complex_unsupported_aspect_raises() -> None:
    specs = [_spec_keep_native()]
    with pytest.raises(ValueError, match="unsupported aspect"):
        build_filter_complex(specs, aspect="4:3")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 7. aspect 分辨率
# ---------------------------------------------------------------------------


def test_build_filter_complex_aspect_16_9_uses_1280_720() -> None:
    """``aspect=16:9`` 走 1280×720（与 PRESET_RESOLUTIONS 表一致）。"""

    specs = [_spec_keep_native()]
    fc = build_filter_complex(specs, aspect="16:9")
    assert "scale=1280:720:" in fc
    assert "pad=1280:720:" in fc


def test_preset_resolutions_table_locked() -> None:
    """``PRESET_RESOLUTIONS`` 是契约边界，意外修改应被立刻感知。"""

    assert PRESET_RESOLUTIONS == {
        "9:16": (1080, 1920),
        "16:9": (1280, 720),
    }


def test_build_filter_complex_unsupported_audio_strategy_raises() -> None:
    """脏数据兜底：未知 audio_strategy 必须抛 ValueError。"""

    spec = SegmentFilterSpec(
        index=0,
        video_input_index=0,
        trim_start_s=0.0,
        trim_end_s=5.0,
        duration_s=5.0,
        audio_strategy="weird_value",  # type: ignore[arg-type]
    )
    with pytest.raises(ValueError, match="audio_strategy"):
        build_segment_filter(spec, width=1080, height=1920)
