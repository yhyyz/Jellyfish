"""ffmpeg / ffprobe 参数构造器单测（W27-T1）。

测试目标：
    - 完全脱离实际 IO，只对 :mod:`app.services.visual_consistency.sampler`
      中的纯函数做白盒断言；
    - 覆盖三类边界：
        1. compute_step / make_plan：total < target / total = target / total >> target。
        2. parse_probe_total_frames：nb_read_packets > nb_frames > duration*fps 三档回退。
        3. build_sample_args / build_probe_args：命令行参数顺序与转义正确。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.visual_consistency.sampler import (
    DEFAULT_FRAME_COUNT,
    FrameSamplingPlan,
    build_probe_args,
    build_sample_args,
    compute_step,
    make_plan,
    parse_probe_total_frames,
)


# --------------------------------------------------------------------------- #
# compute_step / make_plan
# --------------------------------------------------------------------------- #


def test_compute_step_total_zero_falls_back_to_one() -> None:
    assert compute_step(total_frames=0) == 1
    assert compute_step(total_frames=-100) == 1


def test_compute_step_target_invalid_raises() -> None:
    with pytest.raises(ValueError):
        compute_step(total_frames=120, target_count=0)


def test_compute_step_total_smaller_than_target_returns_one() -> None:
    assert compute_step(total_frames=3, target_count=6) == 1
    assert compute_step(total_frames=6, target_count=6) == 1


def test_compute_step_total_much_larger_than_target() -> None:
    assert compute_step(total_frames=180, target_count=6) == 30
    assert compute_step(total_frames=181, target_count=6) == 30


def test_make_plan_records_step_and_targets(tmp_path: Path) -> None:
    plan = make_plan(
        input_path=tmp_path / "in.mp4",
        output_pattern=tmp_path / "frame_%d.jpg",
        total_frames=120,
        target_count=6,
    )
    assert plan.step == 20
    assert plan.target_count == 6
    assert plan.total_frames == 120
    assert plan.expected_output_count() == 6


def test_plan_expected_output_when_total_less_than_target(tmp_path: Path) -> None:
    plan = make_plan(
        input_path=tmp_path / "in.mp4",
        output_pattern=tmp_path / "frame_%d.jpg",
        total_frames=4,
        target_count=6,
    )
    assert plan.step == 1
    assert plan.expected_output_count() == 4


# --------------------------------------------------------------------------- #
# parse_probe_total_frames
# --------------------------------------------------------------------------- #


def test_parse_probe_uses_nb_read_packets_first() -> None:
    payload = {
        "streams": [
            {
                "nb_read_packets": "180",
                "nb_frames": "100",
                "duration": "6.0",
                "r_frame_rate": "30/1",
            }
        ]
    }
    assert parse_probe_total_frames(payload) == 180


def test_parse_probe_falls_back_to_nb_frames() -> None:
    payload = {
        "streams": [
            {
                "nb_read_packets": "N/A",
                "nb_frames": "150",
                "r_frame_rate": "30/1",
            }
        ]
    }
    assert parse_probe_total_frames(payload) == 150


def test_parse_probe_fallback_to_duration_times_fps() -> None:
    payload = {
        "streams": [
            {
                "nb_read_packets": "0",
                "nb_frames": "N/A",
                "duration": "4.5",
                "r_frame_rate": "30/1",
            }
        ]
    }
    assert parse_probe_total_frames(payload) == 135


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"streams": []},
        {"streams": [None]},
        {"streams": [{"nb_frames": "N/A", "duration": "0", "r_frame_rate": "0/0"}]},
    ],
)
def test_parse_probe_returns_zero_when_metadata_missing(payload: object) -> None:
    assert parse_probe_total_frames(payload) == 0  # type: ignore[arg-type]


def test_parse_probe_handles_decimal_frame_rate() -> None:
    payload = {
        "streams": [
            {
                "nb_read_packets": "N/A",
                "nb_frames": "N/A",
                "duration": "10.0",
                "r_frame_rate": "23.976",
            }
        ]
    }
    assert parse_probe_total_frames(payload) == 240


# --------------------------------------------------------------------------- #
# build_probe_args / build_sample_args
# --------------------------------------------------------------------------- #


def test_build_probe_args_emits_count_packets(tmp_path: Path) -> None:
    args = build_probe_args(input_path=tmp_path / "x.mp4")
    assert args[0] == "ffprobe"
    assert "-count_packets" in args
    assert "-of" in args
    assert "json" in args
    assert str(tmp_path / "x.mp4") == args[-1]


def test_build_sample_args_contains_select_with_escaped_comma(tmp_path: Path) -> None:
    plan = make_plan(
        input_path=tmp_path / "in.mp4",
        output_pattern=tmp_path / "frame_%d.jpg",
        total_frames=120,
        target_count=6,
    )
    args = build_sample_args(plan)
    assert args[0] == "ffmpeg"
    assert "-y" in args
    # select 表达式必须把 , 转成 \,，否则 ffmpeg 会把它当 filter chain 分隔符。
    select_index = args.index("-vf")
    select_expr = args[select_index + 1]
    assert select_expr == "select='not(mod(n\\,20))'"
    # vsync vfr 必须存在，否则 select 后输出帧率会被强制对齐回 input。
    assert args[args.index("-vsync") + 1] == "vfr"
    # frames:v 必须等于 target_count。
    assert args[args.index("-frames:v") + 1] == "6"
    # 输出 pattern 是最后一个参数。
    assert args[-1] == str(tmp_path / "frame_%d.jpg")


def test_build_sample_args_rejects_pattern_without_placeholder(tmp_path: Path) -> None:
    plan = FrameSamplingPlan(
        input_path=tmp_path / "in.mp4",
        output_pattern=tmp_path / "frame.jpg",  # 缺少 %d
        total_frames=120,
        target_count=6,
        step=20,
    )
    with pytest.raises(ValueError):
        build_sample_args(plan)


def test_build_sample_args_step_one_when_total_unknown(tmp_path: Path) -> None:
    plan = make_plan(
        input_path=tmp_path / "in.mp4",
        output_pattern=tmp_path / "frame_%d.jpg",
        total_frames=0,
        target_count=DEFAULT_FRAME_COUNT,
    )
    args = build_sample_args(plan)
    select_expr = args[args.index("-vf") + 1]
    assert select_expr == "select='not(mod(n\\,1))'"
