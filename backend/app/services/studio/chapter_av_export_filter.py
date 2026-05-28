"""章节 AV 合成 ffmpeg filter_complex 纯函数构造器（P3 W19 T19-4 / P5 W31）。

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

关键设计要点（参见 W19 librarian 调研报告 + W31 BGM/SFX 扩展）：
- ``amix`` 必须加 ``normalize=0``：默认会按"当前活跃输入数"自动衰减音量，
  导致音量忽高忽低；后置 ``loudnorm`` 做最终响度规整。
- ``subtitles=filename='...'`` 用单引号 + 6 字符转义，避免 Windows 路径与
  filter 参数分隔符冲突。
- ``audio_strategy`` 分流（segment 内 voice 来源）：``silent_with_tts`` 段不
  引用 ``[i:a]``（自动丢弃原音）+ TTS 流通过 ``adelay``/``apad``/``atrim``
  对齐到 segment 视频时长；``keep_native`` 段直接 ``[i:a] → atrim``。
- ``audio_mix_mode`` 分流（segment 内 BGM/SFX 拼装策略，P5 W31）：
    - ``off``：丢弃 voice，输出 ``anullsrc`` 静音轨；
    - ``voice_only``：维持 W19 行为，voice chain 直出；
    - ``voice_bgm``：voice + BGM ``amix weights="1 0.4"``，BGM 静态 -8dB；
    - ``full``：voice + BGM ``sidechaincompress`` 自动 ducking + SFX
      ``amerge`` 时间轴对齐（``adelay`` 处理 segment 内偏移）。
- ``aloop=loop=-1`` 把 BGM 循环铺满到 segment 时长，避免 BGM 短于视频导致
  ducked tail 静音；``size`` 参数给一个大上界（``2147483647``）让 ffmpeg
  在 atrim 处自然截断。
- ``sidechaincompress`` 推荐起点：``threshold=0.01 ratio=8 attack=20
  release=300``。``makeup`` 由 ``bgm_ducking_db`` 透传（负值表示衰减）。
- 视频归一化"四件套"：``setsar=1, fps=N, format=yuv420p, scale+pad`` ——
  concat filter 强制各段视频参数一致，缺一不可。
- ``loudnorm I=-16:TP=-1.5:LRA=11``：通用流媒体配方；YouTube/TikTok 想再
  响一点改 ``I=-14``。single-pass 偏差 ±1 LU 内，短视频场景足够。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from app.models.types import AudioMixMode, AudioStrategy


logger = logging.getLogger(__name__)


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

#: ``voice_bgm`` 模式下 BGM 静态衰减权重（podcast 行业 -8dB ≈ 0.4 linear）。
#: 与 ``full`` 模式的 sidechain ducking 区分：voice_bgm 走静态权重，
#: ``full`` 走 voice envelope 触发的动态衰减。
VOICE_BGM_AMIX_WEIGHTS: str = "1 0.4"

#: ``full`` 模式 sidechaincompress 推荐起点（podcast/voice-over 标准）。
#: ``threshold`` 触发音量门限；``ratio`` 压缩比；``attack``/``release``
#: 控制 envelope 跟随速度（毫秒）。
SIDECHAIN_THRESHOLD: float = 0.01
SIDECHAIN_RATIO: int = 8
SIDECHAIN_ATTACK_MS: int = 20
SIDECHAIN_RELEASE_MS: int = 300


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
        audio_mix_mode (P5 W31): ``off`` / ``voice_only`` / ``voice_bgm`` /
          ``full``。控制 voice chain 之上是否额外混入 BGM / SFX；缺省
          ``voice_only`` 维持 W19 既有行为。
        bgm_input_index (P5 W31): BGM 文件在 ffmpeg ``-i`` 列表中的索引。
          仅 ``voice_bgm`` / ``full`` 模式有效；为 ``None`` 时即使 mode 设为
          ``voice_bgm`` / ``full``，本段也会自动 fallback 到 ``voice_only``。
        sfx_input_index (P5 W31): SFX 文件在 ffmpeg ``-i`` 列表中的索引。
          仅 ``full`` 模式有效；为 ``None`` 时 ``full`` 自动降级为带 ducking
          的 ``voice_bgm``。
        sfx_offset_ms (P5 W31): SFX 在 segment 内的起始毫秒（``adelay``
          参数源），缺省 0 表示 segment 起点。
        bgm_ducking_db (P5 W31): ``full`` 模式 sidechaincompress 的 makeup
          参数（负值表示衰减），范围 [-30.0, 0.0]，缺省 -12.0；
          ``voice_bgm`` 用静态 weights 不读此字段。
    """

    index: int
    video_input_index: int
    trim_start_s: float
    trim_end_s: float
    duration_s: float
    audio_strategy: AudioStrategy
    ass_path: Path | None = None
    tts_clips: tuple[TtsClipSpec, ...] = field(default_factory=tuple)
    # P5 W31 新增字段（默认值与 voice_only 路径完全等价 W19 行为）
    audio_mix_mode: AudioMixMode = AudioMixMode.voice_only
    bgm_input_index: int | None = None
    sfx_input_index: int | None = None
    sfx_offset_ms: int = 0
    bgm_ducking_db: float = -12.0


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


def _voice_label(spec: SegmentFilterSpec) -> str:
    """返回 voice chain 的输出 label。

    voice_only 模式下直接输出 ``[a{idx}]``（与 W19 行为完全一致，保持
    既有测试 / concat 拼接 BC）；其它模式输出中间 label ``[a{idx}_voice]``
    以便后续与 BGM/SFX 二次混合。
    """

    if spec.audio_mix_mode == AudioMixMode.voice_only:
        return f"[a{spec.index}]"
    return f"[a{spec.index}_voice]"


def _build_audio_chain_keep_native(
    spec: SegmentFilterSpec, *, output_label: str | None = None
) -> str:
    """``keep_native`` 路径：直接从视频输入流取原音轨 + atrim 对齐。

    与 ``silent_with_tts`` 路径产出相同形态的 label，便于上层统一拼接。
    ``output_label`` 缺省走 ``_voice_label(spec)``：voice_only 时为
    ``[a{idx}]``，其它模式为 ``[a{idx}_voice]``。
    """

    label = output_label if output_label is not None else _voice_label(spec)
    return (
        f"[{spec.video_input_index}:a]"
        f"atrim=start={spec.trim_start_s}:end={spec.trim_end_s},"
        f"asetpts=PTS-STARTPTS,"
        f"aformat=sample_fmts=fltp:sample_rates={DEFAULT_AUDIO_RATE}:"
        f"channel_layouts={DEFAULT_AUDIO_CHANNELS}"
        f"{label}"
    )


def _build_audio_chain_silent_with_tts(
    spec: SegmentFilterSpec, *, output_label: str | None = None
) -> str:
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

    label = output_label if output_label is not None else _voice_label(spec)
    if not spec.tts_clips:
        return (
            f"anullsrc=cl={DEFAULT_AUDIO_CHANNELS}:r={DEFAULT_AUDIO_RATE},"
            f"atrim=duration={spec.duration_s},"
            f"asetpts=PTS-STARTPTS"
            f"{label}"
        )

    # Step 1: 各 TTS 加 adelay。
    branches: list[str] = []
    labels: list[str] = []
    for j, clip in enumerate(spec.tts_clips):
        offset = max(0, int(clip.offset_ms))
        sublabel = f"[a{spec.index}_t{j}]"
        labels.append(sublabel)
        branches.append(
            f"[{clip.input_index}:a]adelay={offset}|{offset}{sublabel}"
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
        f"{label}"
    )
    return ";".join(branches + [mix_chain, align_chain])


def _resolve_effective_audio_mix_mode(spec: SegmentFilterSpec) -> AudioMixMode:
    """根据 spec 实际带的 BGM/SFX 输入索引决定生效 mode。

    fallback 策略（与 W31-T3 设计一致）：
    - ``voice_bgm`` / ``full`` 但 ``bgm_input_index`` 缺失 → 降级 ``voice_only``
      并写 warning（不 raise，便于前端在 BGM 暂未上传时仍能预览）；
    - ``full`` 但 ``sfx_input_index`` 缺失 → 仍走 ``full`` 路径但跳过
      ``amerge``（保留 sidechain BGM ducking），仅写 warning。``has_sfx``
      由下游 ``_build_full_mix_chain`` 单独判断 spec.sfx_input_index。
    """

    mode = spec.audio_mix_mode
    if mode in (AudioMixMode.voice_bgm, AudioMixMode.full):
        if spec.bgm_input_index is None:
            logger.warning(
                "segment idx=%d audio_mix_mode=%s 缺少 bgm_input_index，"
                "fallback 到 voice_only",
                spec.index,
                mode.value,
            )
            return AudioMixMode.voice_only
    if mode == AudioMixMode.full and spec.sfx_input_index is None:
        logger.warning(
            "segment idx=%d audio_mix_mode=full 缺少 sfx_input_index，"
            "本段跳过 SFX amerge，仍保留 BGM sidechain ducking",
            spec.index,
        )
        # 注意：返回值仍是 full，用于走 sidechaincompress 路径；
        # ``_build_full_mix_chain`` 通过 spec.sfx_input_index is None 决定
        # 是否拼接 amerge 子链。
    return mode


def _build_bgm_loop_chain(spec: SegmentFilterSpec, *, output_label: str) -> str:
    """构造 BGM 循环 + 截断 + 归一化子链，输出到 ``output_label``。

    ``aloop=loop=-1:size=2147483647`` 把 BGM 流无限循环铺满 segment 时长，
    避免 BGM 短于视频导致 ducked tail 静音；``size`` 给一个大上界（int32
    最大值），让后置 atrim 在 segment 时长处自然截断。
    """

    assert spec.bgm_input_index is not None  # 调用方已经过 fallback 检查
    return (
        f"[{spec.bgm_input_index}:a]"
        f"aloop=loop=-1:size=2147483647,"
        f"atrim=duration={spec.duration_s},"
        f"asetpts=PTS-STARTPTS,"
        f"aformat=sample_fmts=fltp:sample_rates={DEFAULT_AUDIO_RATE}:"
        f"channel_layouts={DEFAULT_AUDIO_CHANNELS}"
        f"{output_label}"
    )


def _build_voice_bgm_mix_chain(spec: SegmentFilterSpec) -> str:
    """``voice_bgm`` 路径：voice + BGM 静态权重 amix。

    pseudocode::

        [voice]aformat=...[a{idx}_voice]  (上游 voice chain 已产出)
        [bgm:a]aloop+atrim+aformat=...[a{idx}_bgm]
        [a{idx}_voice][a{idx}_bgm]amix=inputs=2:weights="1 0.4":
            duration=first:normalize=0[a{idx}]

    ``duration=first`` 让输出长度跟随 voice（first input），避免 BGM 长于
    voice 时拖出静默尾。
    """

    voice_label = f"[a{spec.index}_voice]"
    bgm_label = f"[a{spec.index}_bgm]"
    final_label = f"[a{spec.index}]"
    bgm_chain = _build_bgm_loop_chain(spec, output_label=bgm_label)
    mix_chain = (
        f"{voice_label}{bgm_label}"
        f"amix=inputs=2:weights=\"{VOICE_BGM_AMIX_WEIGHTS}\":"
        f"duration=first:normalize=0"
        f"{final_label}"
    )
    return ";".join([bgm_chain, mix_chain])


def _build_full_mix_chain(spec: SegmentFilterSpec, *, has_sfx: bool) -> str:
    """``full`` 路径：voice + BGM(sidechaincompress) [+ SFX(amerge)]。

    pseudocode::

        [voice]aformat=...[a{idx}_voice]  (上游 voice chain 已产出)
        [bgm:a]aloop+atrim+aformat=...[a{idx}_bgm]
        [a{idx}_bgm][a{idx}_voice]sidechaincompress=
            threshold=0.01:ratio=8:attack=20:release=300:
            makeup={ducking_db}[a{idx}_bgm_ducked]
        [a{idx}_voice][a{idx}_bgm_ducked]amix=inputs=2:weights="1 1":
            duration=first:normalize=0[a{idx}_vb_mix]
        # 有 SFX 时再叠加（amerge + 下混 stereo）
        [sfx:a]adelay={offset}|{offset},aformat=...[a{idx}_sfx]
        [a{idx}_vb_mix][a{idx}_sfx]amerge=inputs=2,
            aformat=channel_layouts=stereo[a{idx}]

    ``sidechaincompress`` 把 BGM 接成被压缩流（第 1 输入），voice 作为
    sidechain 触发流（第 2 输入）。voice 出现时 BGM 会按 ratio:1 被衰减。
    ``makeup`` 为最终增益补偿（dB，负值=衰减）。
    """

    voice_label = f"[a{spec.index}_voice]"
    bgm_label = f"[a{spec.index}_bgm]"
    bgm_ducked_label = f"[a{spec.index}_bgm_ducked]"
    vb_mix_label = f"[a{spec.index}_vb_mix]"
    final_label = f"[a{spec.index}]"

    bgm_chain = _build_bgm_loop_chain(spec, output_label=bgm_label)
    sidechain_chain = (
        f"{bgm_label}{voice_label}"
        f"sidechaincompress="
        f"threshold={SIDECHAIN_THRESHOLD}:"
        f"ratio={SIDECHAIN_RATIO}:"
        f"attack={SIDECHAIN_ATTACK_MS}:"
        f"release={SIDECHAIN_RELEASE_MS}:"
        f"makeup={spec.bgm_ducking_db}"
        f"{bgm_ducked_label}"
    )
    voice_bgm_chain = (
        f"{voice_label}{bgm_ducked_label}"
        f"amix=inputs=2:weights=\"1 1\":duration=first:normalize=0"
        f"{vb_mix_label if has_sfx else final_label}"
    )

    if not has_sfx:
        return ";".join([bgm_chain, sidechain_chain, voice_bgm_chain])

    # 含 SFX：amerge 时间轴对齐 + downmix 回 stereo（amerge 默认输出多声道）
    assert spec.sfx_input_index is not None
    sfx_offset = max(0, int(spec.sfx_offset_ms))
    sfx_label = f"[a{spec.index}_sfx]"
    sfx_chain = (
        f"[{spec.sfx_input_index}:a]"
        f"adelay={sfx_offset}|{sfx_offset},"
        f"aformat=sample_fmts=fltp:sample_rates={DEFAULT_AUDIO_RATE}:"
        f"channel_layouts={DEFAULT_AUDIO_CHANNELS}"
        f"{sfx_label}"
    )
    merge_chain = (
        f"{vb_mix_label}{sfx_label}"
        f"amerge=inputs=2,"
        f"aformat=channel_layouts={DEFAULT_AUDIO_CHANNELS}"
        f"{final_label}"
    )
    return ";".join([bgm_chain, sidechain_chain, voice_bgm_chain, sfx_chain, merge_chain])


def _build_off_chain(spec: SegmentFilterSpec) -> str:
    """``off`` 模式：完全静音输出（仅画面 + 字幕烧录场景）。

    丢弃 voice / BGM / SFX 全部输入，直接 ``anullsrc`` 生成 segment 时长的
    纯静音轨；与 ``silent_with_tts + 空 tts_clips`` 路径同形态，便于上层
    concat filter 维持 v/a 等长。
    """

    return (
        f"anullsrc=cl={DEFAULT_AUDIO_CHANNELS}:r={DEFAULT_AUDIO_RATE},"
        f"atrim=duration={spec.duration_s},"
        f"asetpts=PTS-STARTPTS"
        f"[a{spec.index}]"
    )


def _build_audio_chain(spec: SegmentFilterSpec) -> str:
    """根据 ``audio_mix_mode`` 路由到对应 voice + mix 子链组合。

    路由表（与 ``AudioMixMode`` 对齐）：
    - ``off`` → 直接输出 anullsrc，丢弃 voice 链；
    - ``voice_only`` → W19 既有路径，voice chain 直接产出 ``[a{idx}]``；
    - ``voice_bgm`` → voice chain 产出 ``[a{idx}_voice]``，再 amix BGM
      （静态 weights）→ ``[a{idx}]``；
    - ``full`` → voice chain 产出 ``[a{idx}_voice]``，BGM sidechain
      ducking + 可选 SFX amerge → ``[a{idx}]``。

    BGM/SFX 缺失时 ``_resolve_effective_audio_mix_mode`` 已自动 fallback。
    """

    effective_mode = _resolve_effective_audio_mix_mode(spec)

    if effective_mode == AudioMixMode.off:
        return _build_off_chain(spec)

    # 用 effective_mode 重置一下 spec.audio_mix_mode 不可行（frozen=True）；
    # 但 _voice_label 只看 audio_mix_mode 字段，需要给下游算子一个能感知
    # fallback 后真实 mode 的 spec 视图——这里复制一个新 spec。
    if effective_mode != spec.audio_mix_mode:
        spec = SegmentFilterSpec(
            index=spec.index,
            video_input_index=spec.video_input_index,
            trim_start_s=spec.trim_start_s,
            trim_end_s=spec.trim_end_s,
            duration_s=spec.duration_s,
            audio_strategy=spec.audio_strategy,
            ass_path=spec.ass_path,
            tts_clips=spec.tts_clips,
            audio_mix_mode=effective_mode,
            bgm_input_index=spec.bgm_input_index,
            sfx_input_index=spec.sfx_input_index,
            sfx_offset_ms=spec.sfx_offset_ms,
            bgm_ducking_db=spec.bgm_ducking_db,
        )

    if spec.audio_strategy == AudioStrategy.keep_native:
        voice_chain = _build_audio_chain_keep_native(spec)
    elif spec.audio_strategy == AudioStrategy.silent_with_tts:
        voice_chain = _build_audio_chain_silent_with_tts(spec)
    else:
        raise ValueError(
            f"unsupported audio_strategy: {spec.audio_strategy!r}"
        )

    if effective_mode == AudioMixMode.voice_only:
        return voice_chain

    if effective_mode == AudioMixMode.voice_bgm:
        return ";".join([voice_chain, _build_voice_bgm_mix_chain(spec)])

    # full 模式
    has_sfx = spec.sfx_input_index is not None
    return ";".join([voice_chain, _build_full_mix_chain(spec, has_sfx=has_sfx)])


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
    audio_chain = _build_audio_chain(spec)
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
    "SIDECHAIN_ATTACK_MS",
    "SIDECHAIN_RATIO",
    "SIDECHAIN_RELEASE_MS",
    "SIDECHAIN_THRESHOLD",
    "SegmentFilterSpec",
    "TtsClipSpec",
    "VOICE_BGM_AMIX_WEIGHTS",
    "build_filter_complex",
    "build_segment_filter",
    "escape_subtitle_path",
]
