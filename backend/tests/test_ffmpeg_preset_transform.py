"""``ffmpeg_preset_transform`` 纯函数单测（W23-T2，P4 Wave B）。

覆盖（≥4 cases）：

1. ``test_ffmpeg_preset_transform_9_16_from_16_9``：scale+pad 链路命中。
2. ``test_preset_with_watermark_adds_overlay_filter``：水印 overlay 链路。
3. ``test_preset_with_stickers_adds_multi_overlay``：多贴纸 overlay 链路。
4. ``test_preset_codec_h264_high_4_1_arg_built``：h264_high_4_1 编码参数。
5. ``test_loudnorm_arg_when_loudness_lufs_non_default``：非默认响度才追加 loudnorm。
6. ``test_unsupported_aspect_or_codec_raises``：非法值硬抛（防止静默走错预设）。
7. ``test_stickers_from_specs_drops_missing_files``：贴纸映射兜底。

不依赖 DB：直接构造 :class:`PlatformExportPreset` 实例（不 add 到 session）
让 ORM 对象当成纯数据载体使用。
"""

from __future__ import annotations

import pytest

from app.models.platform_export_preset import PlatformExportPreset
from app.models.types import Platform
from app.services.commerce.ffmpeg_preset_transform import (
    StickerInput,
    build_preset_transform_plan,
    stickers_from_specs,
)


def _preset(
    *,
    aspect_ratio: str = "9:16",
    codec_preset: str = "h264_high_4_1",
    loudness_lufs: float = -16.0,
    file_format: str = "mp4",
    watermark_file_id: str | None = None,
    sticker_specs: list[dict] | None = None,
    platform: Platform = Platform.douyin,
) -> PlatformExportPreset:
    """构造一个 in-memory PlatformExportPreset 实例（不入库）。"""

    return PlatformExportPreset(
        id="preset-test",
        name="test preset",
        platform=platform,
        aspect_ratio=aspect_ratio,
        max_duration_sec=60,
        subtitle_style_id=None,
        voice_pack_id=None,
        watermark_file_id=watermark_file_id,
        sticker_specs=list(sticker_specs or []),
        file_format=file_format,
        codec_preset=codec_preset,
        loudness_lufs=loudness_lufs,
        is_system=False,
        sort_order=0,
        description="",
    )


def test_ffmpeg_preset_transform_9_16_from_16_9() -> None:
    """9:16 预设必须输出 1080×1920 + scale+pad 链路。"""

    plan = build_preset_transform_plan(
        _preset(aspect_ratio="9:16"),
        source_video_path="/tmp/source.mp4",
    )
    args = plan.to_ffmpeg_args("/tmp/out.mp4")

    cli = " ".join(args)
    assert "scale=1080:1920:force_original_aspect_ratio=decrease" in cli
    assert "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black" in cli
    assert "[vout]" in plan.filter_complex
    assert "-map" in args and "[vout]" in args
    assert plan.inputs == ["/tmp/source.mp4"]


def test_preset_with_watermark_adds_overlay_filter() -> None:
    """有水印时必须追加 overlay 滤镜并把水印插入 inputs。"""

    plan = build_preset_transform_plan(
        _preset(watermark_file_id="wm-123"),
        source_video_path="/tmp/source.mp4",
        watermark_local_path="/tmp/watermark.png",
    )
    cli = " ".join(plan.to_ffmpeg_args("/tmp/out.mp4"))

    assert plan.inputs == ["/tmp/source.mp4", "/tmp/watermark.png"]
    assert "overlay=W-w-24:24" in cli, "水印应贴右上角 24px 边距"
    assert plan.filter_complex.count("overlay=") >= 1


def test_preset_with_stickers_adds_multi_overlay() -> None:
    """多贴纸时每条都应追加一条 overlay 链 + 对应输入。"""

    stickers = [
        StickerInput(local_path="/tmp/s0.png", x=10, y=20),
        StickerInput(
            local_path="/tmp/s1.png",
            x=100,
            y=200,
            start_ms=1000,
            end_ms=3000,
        ),
    ]
    plan = build_preset_transform_plan(
        _preset(),
        source_video_path="/tmp/source.mp4",
        sticker_inputs=stickers,
    )
    cli = " ".join(plan.to_ffmpeg_args("/tmp/out.mp4"))

    assert plan.inputs == [
        "/tmp/source.mp4",
        "/tmp/s0.png",
        "/tmp/s1.png",
    ]
    assert plan.filter_complex.count("overlay=") == 2
    assert "overlay=10:20" in cli
    assert "overlay=100:200" in cli
    assert "between(t,1.000,3.000)" in cli, "时间窗口必须以 enable= 注入"


def test_preset_codec_h264_high_4_1_arg_built() -> None:
    """h264_high_4_1 必须落到 -c:v libx264 + -profile:v high + -level 4.1。"""

    plan = build_preset_transform_plan(
        _preset(codec_preset="h264_high_4_1"),
        source_video_path="/tmp/source.mp4",
    )
    args = plan.to_ffmpeg_args("/tmp/out.mp4")

    assert "-c:v" in args
    idx = args.index("-c:v")
    assert args[idx + 1] == "libx264"
    assert "high" in args
    assert "4.1" in args
    assert "yuv420p" in args


def test_loudnorm_arg_when_loudness_lufs_non_default() -> None:
    """非默认 LUFS 时必须追加 loudnorm 滤镜并 -map [aout]。"""

    plan_default = build_preset_transform_plan(
        _preset(loudness_lufs=-16.0),
        source_video_path="/tmp/source.mp4",
    )
    plan_custom = build_preset_transform_plan(
        _preset(loudness_lufs=-23.0),
        source_video_path="/tmp/source.mp4",
    )

    assert "loudnorm" not in plan_default.filter_complex
    assert "0:a?" in " ".join(plan_default.map_args)

    assert "loudnorm=I=-23.0:TP=-1.5:LRA=11.0" in plan_custom.filter_complex
    assert "[aout]" in plan_custom.filter_complex
    assert "[aout]" in plan_custom.map_args


def test_unsupported_aspect_or_codec_raises() -> None:
    """非法 aspect / codec 必须硬抛 RuntimeError，避免静默走错预设。"""

    with pytest.raises(RuntimeError, match="aspect_ratio"):
        build_preset_transform_plan(
            _preset(aspect_ratio="2.39:1"),
            source_video_path="/tmp/source.mp4",
        )

    with pytest.raises(RuntimeError, match="codec_preset"):
        build_preset_transform_plan(
            _preset(codec_preset="vp9_highquality"),
            source_video_path="/tmp/source.mp4",
        )


def test_stickers_from_specs_drops_missing_files() -> None:
    """sticker_specs 中缺映射的条目应被静默丢弃，不让一条脏数据炸整次导出。"""

    specs = [
        {"file_id": "ok-1", "x": 5, "y": 10, "start_ms": 100, "end_ms": 500},
        {"file_id": "missing-2", "x": 0, "y": 0},
        {"file_id": "", "x": 0, "y": 0},
    ]
    out = stickers_from_specs(
        specs,
        file_id_to_local_path={"ok-1": "/tmp/ok-1.png"},
    )

    assert len(out) == 1
    assert out[0].local_path == "/tmp/ok-1.png"
    assert out[0].x == 5
    assert out[0].y == 10
    assert out[0].start_ms == 100
    assert out[0].end_ms == 500


def test_file_format_mov_changes_container_arg() -> None:
    """file_format=mov 必须落到 -f mov，便于 worker 用对应后缀输出。"""

    plan = build_preset_transform_plan(
        _preset(file_format="mov"),
        source_video_path="/tmp/source.mp4",
    )
    args = plan.to_ffmpeg_args("/tmp/out.mov")
    assert "-f" in args
    assert args[args.index("-f") + 1] == "mov"
