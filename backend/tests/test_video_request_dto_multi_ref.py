"""VideoGenerationTaskRequest DTO 的 reference_mode Literal 测试（W16 T16-7）。

覆盖：

- 新增的 ``multi_ref`` 取值能被接受，构造时不抛异常；
- 既有取值（first/last/key/first_last/first_last_key/text_only）保持兼容；
- 非法取值（如 ``"unknown"``）会被 pydantic 拒绝；
- 所有合法取值的全集与 P3 设计契约严格一致。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.v1.routes.film.video_request import VideoGenerationTaskRequest


VALID_MODES = (
    "first",
    "last",
    "key",
    "first_last",
    "first_last_key",
    "text_only",
    "multi_ref",
)


def _build_payload(mode: str) -> dict:
    """构造一个最小有效请求体；ratio/shot_id 为必填，images 默认为空列表。"""
    return {
        "shot_id": "shot-001",
        "reference_mode": mode,
        "prompt": "测试提示词" if mode == "text_only" else None,
        "images": [],
        "ratio": "16:9",
    }


@pytest.mark.parametrize("mode", VALID_MODES)
def test_reference_mode_accepts_all_valid_values(mode: str) -> None:
    """每个合法 reference_mode 都应能成功通过 pydantic 校验。"""
    req = VideoGenerationTaskRequest(**_build_payload(mode))
    assert req.reference_mode == mode


def test_multi_ref_specifically_accepted() -> None:
    """显式断言 multi_ref 这一新增值能被 DTO 收下，对 P3 R2V 流程是入口。"""
    req = VideoGenerationTaskRequest(**_build_payload("multi_ref"))
    assert req.reference_mode == "multi_ref"


def test_reference_mode_rejects_unknown_value() -> None:
    """未在 Literal 内的取值应被 pydantic 拒绝，避免任意字符串直接落库。"""
    with pytest.raises(ValidationError):
        VideoGenerationTaskRequest(**_build_payload("unknown_mode"))


def test_reference_mode_literal_full_set() -> None:
    """通过反射断言 Literal 的取值集合恰好等于设计约定，防止后续误增/误删。"""
    # pydantic v2 在 model_fields[name].annotation 上保留原始 Literal。
    annotation = VideoGenerationTaskRequest.model_fields["reference_mode"].annotation
    # typing.Literal 的取值通过 __args__ 暴露。
    literal_values = set(getattr(annotation, "__args__", ()))
    assert literal_values == set(VALID_MODES)
