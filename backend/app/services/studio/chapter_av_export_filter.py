"""章节 AV 合成 ffmpeg filter_complex 纯函数构造器（P3 W19 T19-4）。

为什么存在：
    把 chapter_av_export_task 的 ffmpeg filter 字符串拼接逻辑独立出来：

    1. ``chapter_av_export_task`` 调本模块拼出 filter_complex 字符串后再起子进程；
    2. 单测可以脱离 DB / minio / ffmpeg 直接断言 filter graph 字符串内容；
    3. 未来 chapter_av_export v2 / 多平台导出共用同一拼接逻辑。

做什么：
    - ``escape_subtitle_path(path)``：转义 ffmpeg ``subtitles=`` 滤镜的文件名，
      处理 ``:`` / ``,`` / ``[`` / ``]`` / ``'`` / ``\\`` 6 种特殊字符。
    - ``build_segment_filter(spec)``：构造单 segment 的 filter 子图字符串。
    - ``build_filter_complex(specs)``：把 N 段 segment 子图串成完整
      filter_complex（含 concat + loudnorm 收尾）。

关键设计要点（参见 W19 librarian 调研报告）：
- ``amix`` 必须加 ``normalize=0``：默认会按"当前活跃输入数"自动衰减音量，
  导致音量忽高忽低；后置 ``loudnorm`` 做最终响度规整。
- ``subtitles=filename='...'`` 用单引号 + 6 字符转义，避免 Windows 路径与
  filter 参数分隔符冲突。
- ``audio_strategy`` 分流：``silent_with_tts`` 段不引用 ``[i:a]``（自动丢弃
  原音）+ TTS 流通过 ``adelay``/``apad``/``atrim`` 对齐到 segment 视频时长；
  ``keep_native`` 段直接 ``[i:a] → atrim``。
- 视频归一化"四件套"：``setsar=1, fps=N, format=yuv420p, scale+pad`` ——
  concat filter 强制各段视频参数一致，缺一不可。
- ``loudnorm I=-16:TP=-1.5:LRA=11``：通用流媒体配方；YouTube/TikTok 想再
  响一点改 ``I=-14``。single-pass 偏差 ±1 LU 内，短视频场景足够。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from app.models.types import AudioStrategy


#: 视频归一化目标分辨率（W, H）：9:16 竖屏与 16:9 横屏两种。
PRESET_RESOLUTIONS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1280, 720),
}

#: 默认输出帧率与音频规格（concat filter 要求各段一致）。
DEFAULT_FPS: int = 30
DEFAULT_AUDIO_RATE: int = 48000
DEFAULT_AUDIO_CHANNELS: str = "stereo"

#: loudnorm EBU R128 默认参数（通用流媒体配方）。
LOUDNORM_I: float = -16.0
LOUDNORM_TP: float = -1.5
LOUDNORM_LRA: float = 11.0


@dataclass(frozen=True)
class TtsClipSpec:
    """单段 TTS 音频在 segment 内的时序与文件指针。

    字段：
        input_index: 在 ffmpeg ``-i`` 列表中的索引（0-based）。
        offset_ms: 在 segment 时间线内的起始毫秒（用于 ``adelay`` 滤镜）。
    """

    input_index: int
    offset_ms: int


@dataclass(frozen=True)
class SegmentFilterSpec:
    """单 segment 的 filter 构造参数（不可变）。

    字段：
        index: segment 在章节中的位置（0-based），决定输出 label 后缀。
        video_input_index: 视频文件在 ``-i`` 列表中的索引。
        trim_start_s / trim_end_s: 视频裁剪起止秒（已由
          ``trim_seconds_for_ffmpeg`` 计算好）。
        duration_s: ``trim_end_s - trim_start_s``，预算 segment 实际时长。
        audio_strategy: ``silent_with_tts`` 走 amix TTS / ``keep_native`` 走
          原音轨直通。
        ass_path: 本 segment 字幕 .ass 文件本地绝对路径（None 表示无字幕，
          跳过 ``subtitles=`` 滤镜）。
        tts_clips: 仅 silent_with_tts 路径有效；空列表 → 静默音轨兜底。
    """

    index: int
    video_input_index: int
    trim_start_s: float
    trim_end_s: float
    duration_s: float
    audio_strategy: AudioStrategy
    ass_path: Path | None = None
    tts_clips: tuple[TtsClipSpec, ...] = field(default_factory=tuple)


def escape_subtitle_path(path: str | os.PathLike[str]) -> str:
    """转义 ffmpeg ``subtitles=`` 滤镜的文件名。

    ffmpeg 解析层级是：shell → filter_complex 字符串 → filter 参数（``:`` 分隔）
    → filter 值。每一层都会做 unescape，所以特殊字符要被多次转义。

    必须按以下顺序处理（顺序错误会双重转义）：
    ``\\`` → ``\\\\``
    ``:`` → ``\\:``  (filter 参数分隔符)
    ``'`` → ``\\'``  (字符串引号)
    ``,`` → ``\\,``  (滤镜链分隔符)
    ``[`` / ``]`` → ``\\[`` / ``\\]``  (filter label 分隔符)

    Args:
        path: 待转义的文件路径（支持 str 或 PathLike）。

    Returns:
        转义后可直接拼到 ``subtitles=filename='...'`` 内的字符串。
    """

    text = str(path).replace("\\", "/")
    for raw, escaped in (
        ("\\", "\\\\"),
        (":", "\\:"),
        ("'", "\\'"),
        (",", "\\,"),
        ("[", "\\["),
        ("]", "\\]"),
    ):
        text = text.replace(raw, escaped)
    return text


def _build_subtitles_filter(ass_path: Path | None, fonts_dir: Path | None) -> str:
    """构造 ``subtitles=filename='...'[:fontsdir='...']`` 字符串片段。"""

    if ass_path is None:
        return ""
    parts = [f"filename='{escape_subtitle_path(ass_path)}'"]
    if fonts_dir is not None:
        parts.append(f"fontsdir='{escape_subtitle_path(fonts_dir)}'")
    return "subtitles=" + ":".join(parts)


def _build_video_chain(
    spec: SegmentFilterSpec,
    *,
    width: int,
    height: int,
    fps: int,
    fonts_dir: Path | None,
) -> str:
    """构造单 segment 的视频处理子链。

    链路：``[i:v] → trim → setpts → scale → pad → setsar → fps → format →
    [subtitles] → [v_idx]``。所有归一化滤镜都必加 —— concat filter 强制要求
    各段视频参数一致（SAR / fps / pixel format），缺一会导致 concat 报错。
    """

    sub_filter = _build_subtitles_filter(spec.ass_path, fonts_dir)
    chain = (
        f"[{spec.video_input_index}:v]"
        f"trim=start={spec.trim_start_s}:end={spec.trim_end_s},"
        f"setpts=PTS-STARTPTS,"
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
        f"setsar=1,fps={fps},format=yuv420p"
    )
    if sub_filter:
        chain += "," + sub_filter
    chain += f"[v{spec.index}]"
    return chain


def _build_audio_chain_keep_native(spec: SegmentFilterSpec) -> str:
    """``keep_native`` 路径：直接从视频输入流取原音轨 + atrim 对齐。

    与 ``silent_with_tts`` 路径产出相同形态的 ``[a_idx]`` label，便于上层
    concat filter 统一拼接。
    """

    return (
        f"[{spec.video_input_index}:a]"
        f"atrim=start={spec.trim_start_s}:end={spec.trim_end_s},"
        f"asetpts=PTS-STARTPTS,"
        f"aformat=sample_fmts=fltp:sample_rates={DEFAULT_AUDIO_RATE}:"
        f"channel_layouts={DEFAULT_AUDIO_CHANNELS}"
        f"[a{spec.index}]"
    )


def _build_audio_chain_silent_with_tts(spec: SegmentFilterSpec) -> str:
    """``silent_with_tts`` 路径：丢弃原音 + TTS amix + 时长对齐。

    步骤：
    1. 每段 TTS 经 ``adelay`` 添加 segment 内偏移（双声道写两次 ``ms|ms``）；
    2. ``amix=inputs=N:normalize=0`` 合并（``normalize=0`` 是关键，避免
       音量自动衰减）；单段 TTS 跳过 amix 走 anull 直通；
    3. ``aformat`` 归一化 sample_fmts/rate/channel_layouts；
    4. ``apad + atrim=duration=T`` 把短的 TTS 流补齐到 segment 视频时长，
       避免 concat filter 因为 v/a 时长不一致出现错位。

    特殊路径：``tts_clips`` 为空 → 用 ``anullsrc`` 生成纯静音轨兜底（避免
    concat filter 缺失 a 流报错）。
    """

    if not spec.tts_clips:
        return (
            f"anullsrc=cl={DEFAULT_AUDIO_CHANNELS}:r={DEFAULT_AUDIO_RATE},"
            f"atrim=duration={spec.duration_s},"
            f"asetpts=PTS-STARTPTS"
            f"[a{spec.index}]"
        )

    # Step 1: 各 TTS 加 adelay。
    branches: list[str] = []
    labels: list[str] = []
    for j, clip in enumerate(spec.tts_clips):
        offset = max(0, int(clip.offset_ms))
        label = f"[a{spec.index}_t{j}]"
        labels.append(label)
        branches.append(
            f"[{clip.input_index}:a]adelay={offset}|{offset}{label}"
        )

    # Step 2: amix 合并（单段跳过 amix，走 anull 直通）。
    if len(spec.tts_clips) == 1:
        mix_chain = f"{labels[0]}anull[a{spec.index}_mix]"
    else:
        mix_chain = (
            f"{''.join(labels)}"
            f"amix=inputs={len(spec.tts_clips)}:duration=longest"
            f":dropout_transition=0:normalize=0"
            f"[a{spec.index}_mix]"
        )

    # Step 3+4: 归一化 + 时长对齐。
    align_chain = (
        f"[a{spec.index}_mix]"
        f"aformat=sample_fmts=fltp:sample_rates={DEFAULT_AUDIO_RATE}:"
        f"channel_layouts={DEFAULT_AUDIO_CHANNELS},"
        f"apad,atrim=duration={spec.duration_s},"
        f"asetpts=PTS-STARTPTS"
        f"[a{spec.index}]"
    )
    return ";".join(branches + [mix_chain, align_chain])


def build_segment_filter(
    spec: SegmentFilterSpec,
    *,
    width: int,
    height: int,
    fps: int = DEFAULT_FPS,
    fonts_dir: Path | None = None,
) -> str:
    """构造单 segment 的完整 filter 子图（视频链 + 音频链）。

    Args:
        spec: 不可变的 segment 参数。
        width / height: 输出归一化分辨率（来自 ``PRESET_RESOLUTIONS``）。
        fps: 输出帧率，concat filter 要求各段一致。
        fonts_dir: 可选字体目录，传给 ``subtitles=`` 滤镜的 ``fontsdir``。

    Returns:
        以 ``;`` 分隔的 filter 子图字符串（不带末尾 ``;``）；输出 label =
        ``[v_idx][a_idx]``。上层负责把所有 segment 的输出 label 串到 concat。
    """

    video_chain = _build_video_chain(
        spec, width=width, height=height, fps=fps, fonts_dir=fonts_dir
    )
    if spec.audio_strategy == AudioStrategy.keep_native:
        audio_chain = _build_audio_chain_keep_native(spec)
    elif spec.audio_strategy == AudioStrategy.silent_with_tts:
        audio_chain = _build_audio_chain_silent_with_tts(spec)
    else:
        raise ValueError(
            f"unsupported audio_strategy: {spec.audio_strategy!r}"
        )
    return video_chain + ";" + audio_chain


def build_filter_complex(
    specs: list[SegmentFilterSpec],
    *,
    aspect: Literal["9:16", "16:9"] = "9:16",
    fps: int = DEFAULT_FPS,
    fonts_dir: Path | None = None,
    lufs_target: float = LOUDNORM_I,
    true_peak_target: float = LOUDNORM_TP,
    lra_target: float = LOUDNORM_LRA,
) -> str:
    """把 N 个 segment 子图串成完整 filter_complex。

    输出 label：``[vc][aout]`` —— ``[vc]`` 直接 map 到视频流，``[aout]``
    经 loudnorm 归一化后 map 到音频流。

    Args:
        specs: 至少 1 段，按播放顺序排列；每段 ``index`` 必须从 0 开始连续。
        aspect: 输出宽高比，决定 ``PRESET_RESOLUTIONS`` 选择。
        fps: 帧率。
        fonts_dir: 字幕字体目录。
        lufs_target / true_peak_target / lra_target: loudnorm 参数；
          通用流媒体走 -16/-1.5/11，YouTube/TikTok 风格再响一点用 -14。

    Returns:
        完整 filter_complex 字符串，可直接传给 ffmpeg ``-filter_complex``
        或写入 ``-filter_complex_script`` 文件（>8KB 时建议后者）。

    Raises:
        ValueError: specs 为空或 index 不连续。
    """

    if not specs:
        raise ValueError("build_filter_complex requires non-empty specs")
    for expected, spec in enumerate(specs):
        if spec.index != expected:
            raise ValueError(
                f"specs[{expected}].index expected {expected}, got {spec.index}"
            )

    if aspect not in PRESET_RESOLUTIONS:
        raise ValueError(
            f"unsupported aspect: {aspect!r}; supported: "
            f"{sorted(PRESET_RESOLUTIONS)}"
        )
    width, height = PRESET_RESOLUTIONS[aspect]

    segment_chains = [
        build_segment_filter(
            spec, width=width, height=height, fps=fps, fonts_dir=fonts_dir
        )
        for spec in specs
    ]

    # concat 拼接：[v0][a0][v1][a1]...concat=n=N:v=1:a=1[vc][ac]
    concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(len(specs)))
    concat_chain = (
        f"{concat_inputs}concat=n={len(specs)}:v=1:a=1[vc][ac]"
    )

    # loudnorm EBU R128 归一化（single-pass 即可，短视频场景偏差 ±1 LU 内）
    loudnorm_chain = (
        f"[ac]loudnorm=I={lufs_target}:TP={true_peak_target}:"
        f"LRA={lra_target}:print_format=summary[aout]"
    )

    return ";\n".join(segment_chains + [concat_chain, loudnorm_chain])


__all__ = [
    "DEFAULT_AUDIO_CHANNELS",
    "DEFAULT_AUDIO_RATE",
    "DEFAULT_FPS",
    "LOUDNORM_I",
    "LOUDNORM_LRA",
    "LOUDNORM_TP",
    "PRESET_RESOLUTIONS",
    "SegmentFilterSpec",
    "TtsClipSpec",
    "build_filter_complex",
    "build_segment_filter",
    "escape_subtitle_path",
]
