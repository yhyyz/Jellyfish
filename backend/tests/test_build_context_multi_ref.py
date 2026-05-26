"""build_context multi_ref 模式测试（W16 T16-5 Decision H）。

覆盖 ``REQUIRED_FRAMES_BY_MODE`` 新增条目以及 ``validate_images_count``
对 multi_ref 的 1..9 长度区间约束：multi_ref 不要求固定数量，
但要求至少 1 张、不超过 9 张参考图。
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services.studio.generation.video.build_context import (
    REQUIRED_FRAMES_BY_MODE,
    validate_images_count,
)


def test_multi_ref_in_required_frames_by_mode_with_empty_tuple() -> None:
    """multi_ref 必须存在且对应空 tuple（不绑定 ShotFrameType）。"""
    assert "multi_ref" in REQUIRED_FRAMES_BY_MODE
    assert REQUIRED_FRAMES_BY_MODE["multi_ref"] == ()


def test_validate_images_count_multi_ref_rejects_empty_list() -> None:
    """multi_ref 期待已预解析参考图，空列表应被显式拒绝。"""
    with pytest.raises(HTTPException) as exc_info:
        validate_images_count("multi_ref", [])
    assert exc_info.value.status_code == 400
    assert "multi_ref" in str(exc_info.value.detail)


def test_validate_images_count_multi_ref_accepts_one_image() -> None:
    """1 张参考图位于 multi_ref 合法区间内。"""
    validate_images_count("multi_ref", ["a"])


def test_validate_images_count_multi_ref_accepts_nine_images() -> None:
    """9 张参考图为 multi_ref 上限边界（含）。"""
    validate_images_count("multi_ref", [f"f{i}" for i in range(9)])


def test_validate_images_count_multi_ref_rejects_ten_images() -> None:
    """超过 9 张应被拒绝（默认 cap 来自能力约束）。"""
    with pytest.raises(HTTPException) as exc_info:
        validate_images_count("multi_ref", [f"f{i}" for i in range(10)])
    assert exc_info.value.status_code == 400
    assert "9" in str(exc_info.value.detail)
