"""平台导出 ffmpeg 命令构建（W23-T2，P4 Wave B）。

为什么单独存在
--------------

``commerce_export`` worker 的核心是把"已经合成好的章节成片（chapter_av_export
产出 mp4）"再按 :class:`PlatformExportPreset` 转换为不同平台的发布版本。
ffmpeg 命令按预设组合各种 filter / codec 参数后，会膨胀到 30+ 个 token，
直接写在 worker 里既难单测又难复用。本模块把"预设 → ffmpeg CLI 参数"这
段纯函数提炼出来，worker 只负责 IO + 子进程启动。

设计要点
--------

- 纯函数：输入 :class:`PlatformExportPreset` ORM 行 + 源视频路径 + 额外资源
  本地路径映射，输出 :class:`PresetTransformPlan` （含 ``inputs`` /
  ``filter_complex`` / ``output_args`` / ``map_args``）。**不读 DB、不下载
  任何文件**，便于单测。
- 与 ``chapter_av_export_filter`` 解耦：本模块只关心"已有成片 → 平台版本"
  的二级转换，不重复 chapter_av_export 的字幕烧录 / amix / loudnorm 主链。
- aspect_ratio scale+pad：复用 chapter_av_export 的 9:16 / 16:9 / 1:1 三套
  分辨率（1080×1920 / 1920×1080 / 1080×1080），其他比例直接 RuntimeError。
- watermark / stickers：通过 ``-i ${file}`` 追加输入；overlay 链以 ``[vN]``
  命名串联；最终视频流命名 ``[vout]``。
- subtitle 重烧：本期暂只在元数据中标记 ``subtitle_style_id``，实际再次
  烧录由 worker 决策（如果 preset 的 subtitle_style 与 chapter_av_export
  当时使用的不同，再考虑回到字幕渲染链路；P4 Wave B 默认跳过）。
- codec_preset 仅约束输出编码（``h264_high_4_1`` / ``hevc_main_10`` /
  ``prores_proxy``）；file_format 决定容器（mp4 / mov）。
- loudness_lufs 非默认（-16.0）时追加 ``-af loudnorm=I={lufs}:TP=-1.5:LRA=11``，
  与 chapter_av_export 的 EBU R128 配方对齐。

字段对齐
--------

``sticker_specs`` JSON 元素结构（W23-T2 起约定）::

    {
        "file_id": "<FileItem.id>",
        "local_path": "<absolute path resolved by worker>",
        "x": <int css px on canvas>,
        "y": <int css px on canvas>,
        "start_ms": <int, default 0>,
        "end_ms": <int|null, null=持续到片尾>,
    }

worker 在调用本模块前完成 ``file_id → local_path`` 解析；本模块仅消费
``local_path`` / ``x`` / ``y`` / ``start_ms`` / ``end_ms``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from app.models.platform_export_preset import PlatformExportPreset


#: 预设画幅 → 输出分辨率（W, H）。
#: 与 ``chapter_av_export_filter.PRESET_RESOLUTIONS`` 同义但独立，避免本模块
#: 对 studio 链路的反向耦合（commerce 视角的"导出"不依赖 studio 合成细节）。
PRESET_RESOLUTIONS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
}

#: 编码预设 → ffmpeg ``-c:v`` 系列参数。
#: 列表表达便于直接 ``args.extend``，无需在 worker 拼字符串。
_VIDEO_CODEC_ARGS: dict[str, list[str]] = {
    "h264_high_4_1": [
        "-c:v", "libx264",
        "-profile:v", "high",
        "-level", "4.1",
        "-preset", "medium",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
    ],
    "hevc_main_10": [
        "-c:v", "libx265",
        "-profile:v", "main10",
        "-preset", "medium",
        "-crf", "22",
        "-pix_fmt", "yuv420p10le",
    ],
    "prores_proxy": [
        "-c:v", "prores_ks",
        "-profile:v", "0",
        "-pix_fmt", "yuv422p10le",
    ],
}

#: 默认音频编码（与 chapter_av_export 保持一致：AAC 192k 48k stereo）。
_DEFAULT_AUDIO_ARGS: list[str] = [
    "-c:a", "aac",
    "-b:a", "192k",
    "-ar", "48000",
    "-ac", "2",
]

#: 默认输出响度（LUFS）；与 chapter_av_export EBU R128 默认值一致。
_DEFAULT_LUFS = -16.0

#: loudnorm 副参数：True Peak / Loudness Range；与 chapter_av_export 同源。
_LOUDNORM_TP = -1.5
_LOUDNORM_LRA = 11.0


@dataclass(frozen=True)
class StickerInput:
    """单条贴纸的渲染指令（已解析到本地文件路径）。

    Attributes:
        local_path: 贴纸图片/动图本地路径（worker 已下载）。
        x: 在输出画布上的 x 偏移（左上角原点，单位 px）。
        y: 在输出画布上的 y 偏移（左上角原点，单位 px）。
        start_ms: 开始可见时间（毫秒，默认 0）。
        end_ms: 结束可见时间（毫秒；``None`` 表示持续到片尾）。
    """

    local_path: str
    x: int = 0
    y: int = 0
    start_ms: int = 0
    end_ms: int | None = None


@dataclass(frozen=True)
class PresetTransformPlan:
    """preset → ffmpeg 命令的纯参数打包。

    Attributes:
        inputs: 全部 ``-i`` 文件顺序，第 0 项约定为源视频。
        filter_complex: 完整 filter graph 字符串；最终视频流命名 ``[vout]``，
            音频流（若有 loudnorm）命名 ``[aout]``，否则映射 ``0:a``。
        output_args: 编码 / 容器 / 响度等输出端参数（不含 ``-map``）。
        map_args: ``-map`` 序列；与 filter_complex 出口一一对应。
    """

    inputs: list[str]
    filter_complex: str
    output_args: list[str] = field(default_factory=list)
    map_args: list[str] = field(default_factory=list)

    def to_ffmpeg_args(self, output_path: str) -> list[str]:
        """组装最终 ``ffmpeg`` 子进程参数列表（含可执行名）。

        Args:
            output_path: 目标输出文件本地路径。

        Returns:
            可直接交给 :py:func:`asyncio.create_subprocess_exec` 的 args。
        """

        args: list[str] = ["ffmpeg", "-y"]
        for path in self.inputs:
            args += ["-i", path]
        if self.filter_complex:
            args += ["-filter_complex", self.filter_complex]
        args += list(self.map_args)
        args += list(self.output_args)
        args.append(output_path)
        return args


def _resolution_for(aspect_ratio: str) -> tuple[int, int]:
    """画幅 → (W, H)；非法值抛 RuntimeError。

    与 ``_coerce_aspect`` 同样在不合法时硬抛而非返回默认，避免静默走错预设。
    """

    if aspect_ratio not in PRESET_RESOLUTIONS:
        raise RuntimeError(
            f"unsupported preset aspect_ratio: {aspect_ratio!r}; "
            f"supported: {sorted(PRESET_RESOLUTIONS)}"
        )
    return PRESET_RESOLUTIONS[aspect_ratio]


def _scale_pad_filter(width: int, height: int) -> str:
    """与 chapter_av_export 同源的 scale+pad 归一化（保持比例 + 黑边居中）。

    Why pad 而不是 crop：``commerce_export`` 输入是已经合成的成片，
    跨平台转换时优先保留所有内容（平台审核也偏好"完整画面 + 黑边"），
    crop 会丢失原作信息。
    """

    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
        f"setsar=1"
    )


def _enable_window(start_ms: int, end_ms: int | None) -> str | None:
    """生成 overlay 滤镜的 ``enable='between(t,...)'`` 表达式。

    返回 ``None`` 表示全片显示（worker 端拼接时直接省略 enable=）。
    """

    if start_ms <= 0 and end_ms is None:
        return None
    start_s = max(0, int(start_ms)) / 1000.0
    if end_ms is None:
        return f"between(t,{start_s:.3f},1e9)"
    end_s = max(start_s, int(end_ms) / 1000.0)
    return f"between(t,{start_s:.3f},{end_s:.3f})"


def build_preset_transform_plan(
    preset: PlatformExportPreset,
    *,
    source_video_path: str,
    watermark_local_path: str | None = None,
    sticker_inputs: list[StickerInput] | None = None,
) -> PresetTransformPlan:
    """根据 preset 生成 ffmpeg 转换计划。

    流水线（filter_complex 链路概览）::

        [0:v] scale+pad → [v0]
        [v0][1:v] overlay (watermark) → [v1]   # 若有
        [v1][2:v] overlay (sticker_0)  → [v2]  # 若有
        ...
        [vN] copy → [vout]                     # 出口

    音频：
        - ``loudness_lufs`` 与默认 ``-16.0`` 相同 → 直接 ``-map 0:a?``，
          不重新编码（除非容器要求）；
        - 其它值 → 在 filter_complex 末尾追加 ``[0:a]loudnorm=...[aout]``，
          ``-map [aout]``。

    Args:
        preset: 已落库的 :class:`PlatformExportPreset` 行。
        source_video_path: 源 mp4 本地路径（chapter_av_export 产物）。
        watermark_local_path: 水印 PNG/SVG 本地路径；``None`` 表示该 preset
            不带水印（即使 preset.watermark_file_id 不为 None，也由 worker
            决定是否解析）。
        sticker_inputs: 已解析为本地路径的贴纸列表；空列表与 ``None`` 同义。

    Returns:
        :class:`PresetTransformPlan`，调用方再 ``to_ffmpeg_args`` 拿到完整
        子进程参数列表。
    """

    width, height = _resolution_for(preset.aspect_ratio)
    inputs: list[str] = [source_video_path]

    # ----- 视频链路 -----
    chain: list[str] = []
    chain.append(f"[0:v]{_scale_pad_filter(width, height)}[v0]")
    cur = "[v0]"
    next_idx = 1

    if watermark_local_path:
        inputs.append(watermark_local_path)
        # 水印固定贴右上角 24px 边距，平台默认水印形态（未来可用 preset
        # 字段扩展为 (corner / margin / opacity)）。
        chain.append(
            f"{cur}[{next_idx}:v]overlay=W-w-24:24:format=auto[v{next_idx}]"
        )
        cur = f"[v{next_idx}]"
        next_idx += 1

    for sticker in (sticker_inputs or []):
        inputs.append(sticker.local_path)
        enable = _enable_window(sticker.start_ms, sticker.end_ms)
        enable_clause = f":enable='{enable}'" if enable else ""
        chain.append(
            f"{cur}[{next_idx}:v]"
            f"overlay={int(sticker.x)}:{int(sticker.y)}:format=auto"
            f"{enable_clause}"
            f"[v{next_idx}]"
        )
        cur = f"[v{next_idx}]"
        next_idx += 1

    # 末端重命名为 [vout]：方便调用方稳定 -map [vout]，无需关心中间链长度。
    chain.append(f"{cur}null[vout]")

    map_args: list[str] = ["-map", "[vout]"]

    # ----- 音频链路 -----
    output_args: list[str] = []
    lufs = float(getattr(preset, "loudness_lufs", _DEFAULT_LUFS))
    if abs(lufs - _DEFAULT_LUFS) < 1e-6:
        # 与默认值一致 → 直接 pass-through 源音轨。
        map_args += ["-map", "0:a?"]
    else:
        chain.append(
            f"[0:a]loudnorm=I={lufs}:TP={_LOUDNORM_TP}:LRA={_LOUDNORM_LRA}[aout]"
        )
        map_args += ["-map", "[aout]"]

    filter_complex = ";".join(chain)

    # ----- 编码 / 容器 -----
    codec_args = _VIDEO_CODEC_ARGS.get(preset.codec_preset)
    if codec_args is None:
        raise RuntimeError(
            f"unsupported codec_preset: {preset.codec_preset!r}; "
            f"supported: {sorted(_VIDEO_CODEC_ARGS)}"
        )
    output_args += list(codec_args)
    output_args += list(_DEFAULT_AUDIO_ARGS)
    output_args += ["-movflags", "+faststart"]
    # file_format 仅作为容器扩展名提示，当前实现交由 output_path 后缀决定；
    # 这里显式记录到 output_args 末尾的注释式 ``-f`` 让 worker 在没有正确
    # 后缀时也能强制 mux 容器。
    fmt = (preset.file_format or "mp4").lower()
    output_args += ["-f", fmt]

    return PresetTransformPlan(
        inputs=inputs,
        filter_complex=filter_complex,
        output_args=output_args,
        map_args=map_args,
    )


def stickers_from_specs(
    sticker_specs: Sequence[Mapping[str, Any]] | None,
    *,
    file_id_to_local_path: Mapping[str, str],
) -> list[StickerInput]:
    """把 preset.sticker_specs JSON 数组解析为 :class:`StickerInput` 列表。

    Args:
        sticker_specs: 来自 :class:`PlatformExportPreset.sticker_specs` 的
            JSON 数组；元素必须包含 ``file_id``。
        file_id_to_local_path: worker 端事先下载所有贴纸文件后给出的
            ``file_id -> 本地路径`` 映射；缺映射的项会被静默丢弃，避免
            一个无效贴纸炸掉整次导出。

    Returns:
        :class:`StickerInput` 列表，按原顺序保留。
    """

    out: list[StickerInput] = []
    for spec in (sticker_specs or []):
        file_id = str(spec.get("file_id") or "").strip()
        if not file_id:
            continue
        local = file_id_to_local_path.get(file_id)
        if not local:
            continue
        out.append(
            StickerInput(
                local_path=local,
                x=int(spec.get("x", 0) or 0),
                y=int(spec.get("y", 0) or 0),
                start_ms=int(spec.get("start_ms", 0) or 0),
                end_ms=(
                    int(spec["end_ms"])
                    if spec.get("end_ms") is not None
                    else None
                ),
            )
        )
    return out


__all__ = [
    "PRESET_RESOLUTIONS",
    "PresetTransformPlan",
    "StickerInput",
    "build_preset_transform_plan",
    "stickers_from_specs",
]
