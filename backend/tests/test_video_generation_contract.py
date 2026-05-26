"""VideoGenerationInput 契约测试。

覆盖：
- 既有行为：prompt-only / first_frame_base64-only 通过
- 新增行为：reference_images_base64（多图参考列表，r2v 用）
- 边界：空列表、全空白项、prompt + 空列表
- 拒绝：所有引用为空且无 prompt
- 严格模式：extra="forbid" 仍生效
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.contracts.video_generation import VideoGenerationInput


# ---------------------------------------------------------------------------
# 既有行为保留
# ---------------------------------------------------------------------------


def test_prompt_only_passes() -> None:
    """仅有 prompt 时应通过校验（既有行为）。"""
    inp = VideoGenerationInput(prompt="一只猫在跳舞", ratio="16:9")
    assert inp.prompt == "一只猫在跳舞"
    assert inp.reference_images_base64 is None


def test_first_frame_only_passes() -> None:
    """仅有 first_frame_base64 时应通过校验（既有行为）。"""
    inp = VideoGenerationInput(
        first_frame_base64="data:image/png;base64,AAAA",
        ratio="16:9",
    )
    assert inp.first_frame_base64 == "data:image/png;base64,AAAA"
    assert inp.prompt is None


# ---------------------------------------------------------------------------
# 新增字段 reference_images_base64
# ---------------------------------------------------------------------------


def test_reference_images_only_passes() -> None:
    """仅有 reference_images_base64（无 prompt、无其它帧）时应通过校验。"""
    inp = VideoGenerationInput(
        reference_images_base64=["data:image/png;base64,xxx"],
        ratio="16:9",
    )
    assert inp.reference_images_base64 == ["data:image/png;base64,xxx"]
    assert inp.prompt is None
    assert inp.first_frame_base64 is None


def test_prompt_and_reference_images_both_pass() -> None:
    """prompt + reference_images_base64 同时存在应通过。"""
    inp = VideoGenerationInput(
        prompt="夕阳下的港口",
        reference_images_base64=[
            "data:image/png;base64,a",
            "data:image/png;base64,b",
        ],
        ratio="9:16",
    )
    assert inp.prompt == "夕阳下的港口"
    assert inp.reference_images_base64 is not None
    assert len(inp.reference_images_base64) == 2


def test_prompt_with_empty_reference_list_passes() -> None:
    """prompt 存在 + reference_images_base64 为空列表，仍应通过（prompt 已满足）。"""
    inp = VideoGenerationInput(
        prompt="海边的少年",
        reference_images_base64=[],
        ratio="16:9",
    )
    assert inp.prompt == "海边的少年"
    assert inp.reference_images_base64 == []


# ---------------------------------------------------------------------------
# 拒绝场景
# ---------------------------------------------------------------------------


def test_all_empty_raises() -> None:
    """无 prompt、无任何参考帧、无参考图列表，应抛 ValidationError。"""
    with pytest.raises(ValidationError):
        VideoGenerationInput(ratio="16:9")


def test_empty_reference_list_without_prompt_raises() -> None:
    """reference_images_base64=[] 且无 prompt、无其它帧，应被拒绝。"""
    with pytest.raises(ValidationError):
        VideoGenerationInput(reference_images_base64=[], ratio="16:9")


def test_whitespace_only_reference_items_without_prompt_raises() -> None:
    """reference_images_base64 元素全为空白字符串时，等同无引用，应被拒绝。"""
    with pytest.raises(ValidationError):
        VideoGenerationInput(
            reference_images_base64=["", "   ", "\t\n"],
            ratio="16:9",
        )


def test_whitespace_reference_items_with_prompt_passes() -> None:
    """全空白参考项 + prompt 仍通过（prompt 已满足）。"""
    inp = VideoGenerationInput(
        prompt="一片森林",
        reference_images_base64=["", "  "],
        ratio="16:9",
    )
    assert inp.prompt == "一片森林"


# ---------------------------------------------------------------------------
# extra="forbid" 兜底
# ---------------------------------------------------------------------------


def test_extra_forbid_still_rejects_unknown_field() -> None:
    """extra=forbid：未知字段仍应被拒绝（防止字段静默丢失）。"""
    with pytest.raises(ValidationError):
        VideoGenerationInput(
            prompt="hi",
            ratio="16:9",
            unknown_field="x",  # type: ignore[call-arg]
        )
