"""W31-T3 chapter_av_export_filter voice_bgm + full 路径单元测试。

覆盖目标：
1. ``voice_bgm`` 模式输出包含 ``amix weights="1 0.4"`` 静态权重；
2. ``voice_bgm`` 模式 BGM 经 ``aloop`` 循环铺满 segment 时长；
3. ``full`` 模式输出包含 ``sidechaincompress`` 关键参数（threshold/ratio/
   attack/release/makeup）；
4. ``full`` 模式 SFX 经 ``adelay`` 处理时间偏移 + ``amerge`` 加入；
5. ``full`` 模式无 SFX 时降级为带 ducking 的 voice_bgm（无 amerge）；
6. ``voice_bgm`` 缺 ``bgm_input_index`` 时 fallback 到 voice_only；
7. ``full`` 缺 ``bgm_input_index`` 时 fallback 到 voice_only；
8. ``off`` 模式输出 anullsrc 静音轨；
9. fallback 路径不在 spec 上 raise，仅写 warning（W31 设计原则）。
"""

# pylint: disable=invalid-name,duplicate-code

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from app.models.types import AudioMixMode, AudioStrategy
from app.services.studio.chapter_av_export_filter import (
    SIDECHAIN_ATTACK_MS,
    SIDECHAIN_RATIO,
    SIDECHAIN_RELEASE_MS,
    SIDECHAIN_THRESHOLD,
    SegmentFilterSpec,
    TtsClipSpec,
    VOICE_BGM_AMIX_WEIGHTS,
    build_filter_complex,
    build_segment_filter,
)


def _spec_voice_bgm(
    *,
    idx: int = 0,
    has_bgm: bool = True,
    bgm_idx: int = 5,
    audio_strategy: AudioStrategy = AudioStrategy.silent_with_tts,
) -> SegmentFilterSpec:
    """构造 voice_bgm 模式 spec（默认 silent_with_tts + 1 段 TTS）。"""
    return SegmentFilterSpec(
        index=idx,
        video_input_index=idx,
        trim_start_s=0.0,
        trim_end_s=5.0,
        duration_s=5.0,
        audio_strategy=audio_strategy,
        ass_path=Path("/tmp/sub.ass"),
        tts_clips=(
            (TtsClipSpec(input_index=idx + 10, offset_ms=0),)
            if audio_strategy == AudioStrategy.silent_with_tts
            else ()
        ),
        audio_mix_mode=AudioMixMode.voice_bgm,
        bgm_input_index=bgm_idx if has_bgm else None,
    )


def _spec_full(
    *,
    idx: int = 0,
    has_bgm: bool = True,
    has_sfx: bool = True,
    bgm_idx: int = 5,
    sfx_idx: int = 6,
    sfx_offset_ms: int = 1500,
    bgm_ducking_db: float = -12.0,
    audio_strategy: AudioStrategy = AudioStrategy.silent_with_tts,
) -> SegmentFilterSpec:
    """构造 full 模式 spec。"""
    return SegmentFilterSpec(
        index=idx,
        video_input_index=idx,
        trim_start_s=0.0,
        trim_end_s=5.0,
        duration_s=5.0,
        audio_strategy=audio_strategy,
        ass_path=Path("/tmp/sub.ass"),
        tts_clips=(
            (TtsClipSpec(input_index=idx + 10, offset_ms=0),)
            if audio_strategy == AudioStrategy.silent_with_tts
            else ()
        ),
        audio_mix_mode=AudioMixMode.full,
        bgm_input_index=bgm_idx if has_bgm else None,
        sfx_input_index=sfx_idx if has_sfx else None,
        sfx_offset_ms=sfx_offset_ms,
        bgm_ducking_db=bgm_ducking_db,
    )


# ---------------------------------------------------------------------------
# 1. voice_bgm 模式：amix weights + aloop
# ---------------------------------------------------------------------------


def test_voice_bgm_mix_uses_static_weights_one_dot_four() -> None:
    """voice_bgm 路径必须在输出中出现 ``amix ... weights="1 0.4"``。"""

    chain = build_segment_filter(_spec_voice_bgm(), width=1080, height=1920)
    assert f'weights="{VOICE_BGM_AMIX_WEIGHTS}"' in chain
    assert "amix=inputs=2" in chain
    assert "duration=first" in chain
    assert "normalize=0" in chain


def test_voice_bgm_loops_bgm_to_segment_duration() -> None:
    """BGM 必须经 ``aloop=loop=-1`` + ``atrim=duration=segment_dur`` 铺满。"""

    chain = build_segment_filter(_spec_voice_bgm(), width=1080, height=1920)
    assert "aloop=loop=-1" in chain
    # atrim=duration=5.0 既在 voice padding 也在 BGM 截断处出现。
    assert "atrim=duration=5.0" in chain


def test_voice_bgm_voice_chain_uses_intermediate_label() -> None:
    """voice chain 必须输出中间 label ``[a0_voice]``，最终 ``[a0]`` 由 mix 链产出。"""

    chain = build_segment_filter(_spec_voice_bgm(idx=0), width=1080, height=1920)
    assert "[a0_voice]" in chain
    assert "[a0_bgm]" in chain
    # 确认最终 [a0] 仍然由 amix 产出（concat filter 依赖此 label）。
    assert "[a0]" in chain


def test_voice_bgm_keep_native_voice_chain_works() -> None:
    """voice_bgm 与 keep_native 组合：voice chain 走原音 atrim → 中间 label。"""

    spec = _spec_voice_bgm(audio_strategy=AudioStrategy.keep_native)
    chain = build_segment_filter(spec, width=1080, height=1920)
    # 原音流 + atrim：
    assert "[0:a]atrim=start=0.0:end=5.0" in chain
    # 中间 voice label + 最终 a0
    assert "[a0_voice]" in chain
    assert "[a0]" in chain
    # voice_bgm 必须含静态 amix
    assert f'weights="{VOICE_BGM_AMIX_WEIGHTS}"' in chain


# ---------------------------------------------------------------------------
# 2. full 模式：sidechaincompress + amerge SFX
# ---------------------------------------------------------------------------


def test_full_mode_emits_sidechaincompress_with_recommended_params() -> None:
    """full 路径必须包含 sidechaincompress + 推荐参数（threshold/ratio/attack/release）。"""

    chain = build_segment_filter(_spec_full(), width=1080, height=1920)
    assert "sidechaincompress=" in chain
    assert f"threshold={SIDECHAIN_THRESHOLD}" in chain
    assert f"ratio={SIDECHAIN_RATIO}" in chain
    assert f"attack={SIDECHAIN_ATTACK_MS}" in chain
    assert f"release={SIDECHAIN_RELEASE_MS}" in chain


def test_full_mode_passes_ducking_db_to_sidechaincompress_makeup() -> None:
    """``bgm_ducking_db`` 必须透传到 sidechaincompress 的 ``makeup`` 参数。"""

    chain = build_segment_filter(
        _spec_full(bgm_ducking_db=-18.0), width=1080, height=1920
    )
    assert "makeup=-18.0" in chain


def test_full_mode_emits_amerge_for_sfx_overlay() -> None:
    """有 SFX 时必须 ``amerge=inputs=2`` 加入。"""

    chain = build_segment_filter(_spec_full(), width=1080, height=1920)
    assert "amerge=inputs=2" in chain


def test_full_mode_sfx_uses_adelay_with_offset() -> None:
    """SFX 经 ``adelay=offset|offset`` 处理 segment 内时间偏移。"""

    chain = build_segment_filter(
        _spec_full(sfx_offset_ms=1500), width=1080, height=1920
    )
    assert "adelay=1500|1500" in chain


def test_full_mode_with_zero_sfx_offset_uses_zero_adelay() -> None:
    """SFX offset=0 时仍然写 ``adelay=0|0``（保持时间轴对齐 filter 一致）。"""

    chain = build_segment_filter(
        _spec_full(sfx_offset_ms=0), width=1080, height=1920
    )
    assert "adelay=0|0" in chain


def test_full_mode_includes_intermediate_vb_mix_label() -> None:
    """有 SFX 时 voice + ducked BGM 先合成中间 ``[a{idx}_vb_mix]``，再 merge SFX。"""

    chain = build_segment_filter(_spec_full(idx=2), width=1080, height=1920)
    assert "[a2_vb_mix]" in chain
    assert "[a2_sfx]" in chain
    assert "[a2_bgm_ducked]" in chain


# ---------------------------------------------------------------------------
# 3. full 模式无 SFX：降级为带 ducking 的 voice_bgm
# ---------------------------------------------------------------------------


def test_full_mode_without_sfx_drops_amerge_keeps_sidechain(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``full`` 缺 SFX 时降级 voice_bgm（保留 ducking）：无 amerge，但 sidechain 仍在。"""

    caplog.set_level(logging.WARNING)
    chain = build_segment_filter(
        _spec_full(has_sfx=False), width=1080, height=1920
    )
    assert "sidechaincompress=" in chain
    assert "amerge=" not in chain
    assert any(
        "缺少 sfx_input_index" in record.message for record in caplog.records
    )


# ---------------------------------------------------------------------------
# 4. fallback：BGM 缺失
# ---------------------------------------------------------------------------


def test_voice_bgm_without_bgm_falls_back_to_voice_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``voice_bgm`` 缺 ``bgm_input_index`` 时 fallback 到 voice_only。"""

    caplog.set_level(logging.WARNING)
    chain = build_segment_filter(
        _spec_voice_bgm(has_bgm=False), width=1080, height=1920
    )
    # voice_only 路径输出 [a0] 直接由 voice chain 产出，没有 amix BGM。
    assert "amix=inputs=2:weights=" not in chain
    assert "sidechaincompress=" not in chain
    assert "[a0_voice]" not in chain  # voice 链直接产出 [a0]
    assert "[a0]" in chain
    assert any(
        "fallback 到 voice_only" in record.message for record in caplog.records
    )


def test_full_without_bgm_falls_back_to_voice_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``full`` 缺 BGM 时同样 fallback 到 voice_only（不可能做 ducking）。"""

    caplog.set_level(logging.WARNING)
    chain = build_segment_filter(
        _spec_full(has_bgm=False), width=1080, height=1920
    )
    assert "sidechaincompress=" not in chain
    assert "amerge=" not in chain
    assert any(
        "fallback 到 voice_only" in record.message for record in caplog.records
    )


# ---------------------------------------------------------------------------
# 5. off 模式：完全静音输出
# ---------------------------------------------------------------------------


def test_off_mode_emits_anullsrc_silent_track() -> None:
    """``off`` 路径输出 ``anullsrc`` 静音轨，丢弃 voice / BGM / SFX。"""

    spec = SegmentFilterSpec(
        index=0,
        video_input_index=0,
        trim_start_s=0.0,
        trim_end_s=5.0,
        duration_s=5.0,
        audio_strategy=AudioStrategy.silent_with_tts,
        tts_clips=(TtsClipSpec(input_index=1, offset_ms=0),),
        audio_mix_mode=AudioMixMode.off,
    )
    chain = build_segment_filter(spec, width=1080, height=1920)
    assert "anullsrc=" in chain
    # off 模式不应混入任何 voice / BGM / SFX
    assert "amix=inputs=2:weights=" not in chain
    assert "sidechaincompress=" not in chain
    assert "amerge=" not in chain
    # 仍输出 [a0]，concat filter 依赖此 label
    assert "[a0]" in chain


# ---------------------------------------------------------------------------
# 6. build_filter_complex 集成：voice_bgm / full 与 voice_only 混合 concat
# ---------------------------------------------------------------------------


def test_build_filter_complex_mixes_voice_only_and_voice_bgm_segments() -> None:
    """同一章节可包含 voice_only + voice_bgm 不同 mode 的 segment。"""

    spec_voice_only = SegmentFilterSpec(
        index=0,
        video_input_index=0,
        trim_start_s=0.0,
        trim_end_s=5.0,
        duration_s=5.0,
        audio_strategy=AudioStrategy.keep_native,
        audio_mix_mode=AudioMixMode.voice_only,
    )
    spec_voice_bgm = _spec_voice_bgm(idx=1, bgm_idx=2)
    fc = build_filter_complex(
        [spec_voice_only, spec_voice_bgm], aspect="9:16"
    )
    # 两段 concat 输入仍然是 [v0][a0][v1][a1]
    assert "[v0][a0][v1][a1]concat=n=2:v=1:a=1[vc][ac]" in fc
    # voice_bgm 段产出 BGM amix
    assert f'weights="{VOICE_BGM_AMIX_WEIGHTS}"' in fc


def test_build_filter_complex_full_mode_segment_keeps_concat_label_shape() -> None:
    """full 模式 segment 仍然产出标准 ``[v_idx][a_idx]`` 供 concat 使用。"""

    fc = build_filter_complex([_spec_full(idx=0)], aspect="9:16")
    assert "[v0][a0]concat=n=1:v=1:a=1[vc][ac]" in fc
    assert "sidechaincompress=" in fc
    assert "amerge=inputs=2" in fc
