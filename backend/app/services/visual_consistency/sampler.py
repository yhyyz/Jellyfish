"""ffmpeg / ffprobe 命令行参数构造（P4 W27-T1）。

为什么独立一个文件：
    - worker 在子进程里调 ffmpeg 抽 N 帧之前，需要先 ffprobe 获取总帧数；
      参数构造逻辑剥离出来后，单测可以**完全脱离实际 IO** 直接断言命令行
      字符串内容（与 ``chapter_av_export_filter`` 的 builder 风格一致）。
    - 后续 W27-T2 / W27-T4 复用同一个抽帧策略时不必重复实现。

抽帧算法（与任务规范一致）：
    1. ffprobe 取视频 ``nb_frames``（H.264/MP4 容器中此值通常存在；不可
       靠时回退到 ``frame_count = round(duration * frame_rate)``）；
    2. 计算 step = max(1, floor(total / N))；
    3. ffmpeg ``select='not(mod(n,step))'`` + ``vsync vfr`` 取出最多 N 帧。

注意：
    select 表达式中的 ``,`` 必须显式做反斜杠转义（即 backslash + 逗号），
    否则会被 ffmpeg 当作 filter 分隔符（与既有
    ``chapter_av_export_filter.escape_subtitle_path`` 同因）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: 默认抽帧数量；与任务规范 N=6 对齐。
DEFAULT_FRAME_COUNT: int = 6


@dataclass(frozen=True)
class FrameSamplingPlan:
    """单次抽帧计划的内部表示。

    把 step / 期望帧数 / 输出 pattern 显式提供给上层，便于：
        - worker 拼装 ffmpeg 命令行；
        - 单测做白盒断言（不必跑 ffmpeg）；
        - 失败诊断时把字段写进任务 result。
    """

    input_path: Path
    output_pattern: Path
    total_frames: int
    target_count: int
    step: int

    def expected_output_count(self) -> int:
        """根据 step 估算 ffmpeg 实际产出的帧数上限。

        ffmpeg ``select='not(mod(n,step))'`` 对 ``n in [0, total)`` 计数；
        命中条件成立的次数即 ``ceil(total / step)``，再被 ``-frames:v
        target_count`` 截断。
        """

        if self.step <= 0 or self.total_frames <= 0:
            return 0
        produced = (self.total_frames + self.step - 1) // self.step
        return min(produced, self.target_count)


def compute_step(*, total_frames: int, target_count: int = DEFAULT_FRAME_COUNT) -> int:
    """根据总帧数和期望帧数计算 step。

    设计要点：
        - ``total_frames <= 0``：视频元数据不可读，回退 step=1（取前 N 帧），
          worker 仍能尝试推进；
        - ``target_count <= 0``：抛 ``ValueError``，调用方传错了；
        - ``total_frames < target_count``：直接 step=1，所有帧都取（最多
          ``-frames:v`` 截断）。

    Returns:
        正整数 step；上层把它直接拼进 select 表达式。
    """

    if target_count <= 0:
        raise ValueError(f"target_count must be > 0, got {target_count}")
    if total_frames <= 0:
        return 1
    if total_frames <= target_count:
        return 1
    return max(1, total_frames // target_count)


def build_probe_args(*, input_path: Path) -> list[str]:
    """构造 ``ffprobe -v error -count_packets ...`` 命令行。

    选用 ``count_packets`` 是因为 ``count_frames`` 会强制全文件解码，对
    长视频代价过高；packets 数对 H.264 / H.265 而言与帧数 1:1 对齐。
    """

    return [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-count_packets",
        "-show_entries",
        "stream=nb_read_packets,nb_frames,r_frame_rate,duration",
        "-of",
        "json",
        str(input_path),
    ]


def parse_probe_total_frames(probe_payload: dict | None) -> int:
    """从 ffprobe JSON 输出里抽出总帧数。

    解析顺序：
        1. ``streams[0].nb_read_packets`` —— ``-count_packets`` 显式产出值，
           最准确；
        2. ``streams[0].nb_frames`` —— 容器内嵌的元数据，部分流可能缺失；
        3. ``streams[0].duration * r_frame_rate`` —— 兜底估算。

    Returns:
        ``> 0`` 的整数；全部解析失败时返回 ``0``，由 :func:`compute_step`
        回退到 step=1。
    """

    if not isinstance(probe_payload, dict):
        return 0
    streams = probe_payload.get("streams")
    if not isinstance(streams, list) or not streams:
        return 0
    head = streams[0]
    if not isinstance(head, dict):
        return 0

    for key in ("nb_read_packets", "nb_frames"):
        raw = head.get(key)
        if raw in (None, "", "N/A"):
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value

    duration_raw = head.get("duration")
    rate_raw = head.get("r_frame_rate")
    try:
        duration = float(duration_raw) if duration_raw not in (None, "", "N/A") else 0.0
    except (TypeError, ValueError):
        duration = 0.0
    rate = _parse_frame_rate(rate_raw)
    if duration > 0 and rate > 0:
        estimated = int(round(duration * rate))
        if estimated > 0:
            return estimated
    return 0


def _parse_frame_rate(raw: object) -> float:
    """解析 ffprobe ``r_frame_rate``（如 ``"30/1"``）为浮点 fps。"""

    if isinstance(raw, (int, float)):
        return float(raw)
    if not isinstance(raw, str) or not raw:
        return 0.0
    try:
        if "/" in raw:
            num, denom = raw.split("/", 1)
            n_val = float(num)
            d_val = float(denom)
            return n_val / d_val if d_val else 0.0
        return float(raw)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def build_sample_args(plan: FrameSamplingPlan) -> list[str]:
    """构造 ffmpeg 抽帧命令行。

    关键参数说明：
        - ``select='not(mod(n,STEP))'``：只保留帧号能被 STEP 整除的帧；
          ``,`` 必须用反斜杠转义（即一个反斜杠 + 逗号），否则 ffmpeg 会
          把它当作 filter chain 的分隔符（同
          ``escape_subtitle_path`` 的踩坑经验）；
        - ``-vsync vfr``：放弃帧率重采样，否则 select 后输出会被 padding
          / drop 回 input fps，破坏"恰好 N 帧"的预期；
        - ``-frames:v target_count``：硬性上限，超出 select 命中次数时
          ffmpeg 会停在第 N 帧；
        - ``-q:v 2``：JPEG 质量 2（高质量，文件 ~30-80KB 单帧），
          对 DINOv2 输入足够；
        - ``-y``：自动覆盖目标文件，避免单测 / 重跑 stuck。

    输出 pattern 必须包含 ``%d``（如 ``frame_%d.jpg``），否则 ffmpeg
    会拒绝写入多帧。
    """

    pattern = str(plan.output_pattern)
    if "%" not in pattern:
        raise ValueError(
            f"output_pattern must contain a printf-style placeholder (e.g. %d), got {pattern!r}"
        )

    select_expr = f"select='not(mod(n\\,{plan.step}))'"
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(plan.input_path),
        "-vf",
        select_expr,
        "-vsync",
        "vfr",
        "-frames:v",
        str(plan.target_count),
        "-q:v",
        "2",
        pattern,
    ]


def make_plan(
    *,
    input_path: Path,
    output_pattern: Path,
    total_frames: int,
    target_count: int = DEFAULT_FRAME_COUNT,
) -> FrameSamplingPlan:
    """构造 :class:`FrameSamplingPlan` 的便捷工厂。

    把 step 计算与 plan 装配收敛在一起，让 worker 调用更简洁：

    .. code-block:: python

        plan = make_plan(input_path=p, output_pattern=tmp / "f_%d.jpg",
                         total_frames=probe_total)
        args = build_sample_args(plan)
    """

    step = compute_step(total_frames=total_frames, target_count=target_count)
    return FrameSamplingPlan(
        input_path=input_path,
        output_pattern=output_pattern,
        total_frames=max(0, total_frames),
        target_count=target_count,
        step=step,
    )


__all__ = [
    "DEFAULT_FRAME_COUNT",
    "FrameSamplingPlan",
    "build_probe_args",
    "build_sample_args",
    "compute_step",
    "make_plan",
    "parse_probe_total_frames",
]
