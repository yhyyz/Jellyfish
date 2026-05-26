"""W16 T16-4: DashScope happyhorse-1.0-r2v 多图参考模式契约测试。

覆盖：

1. ``_dashscope_video_mode``：``-r2v`` 词缀必须先于 ``ref_video`` / ``i2v`` 等
   matcher 被识别，否则 happyhorse-1.0-r2v 会被误判为 ref_video。
2. ``_build_dashscope_video_body``：r2v 分支应将
   ``input.reference_images_base64`` 映射为 ``input.media`` 列表，每项
   ``type="reference_image"``，url 为 data URL。
3. 数量上限：1-9 张；超出 9 张报错（与 W1-B aliyun 规格 max_reference_images=9 对齐）。
4. 边界：r2v 模型但 ``reference_images_base64`` 为空 / 全空白 / None 时，
   不抛错（contract validator 已要求至少有 prompt 或参考），body 不附带 media，
   等价于 t2v fallback。
"""

from __future__ import annotations

import pytest

from app.core.contracts.video_generation import VideoGenerationInput
from app.core.integrations.aliyun.dashscope_videos import (
    _build_dashscope_video_body,
    _dashscope_video_mode,
)


class TestDashscopeR2VModeDetection:
    """``_dashscope_video_mode`` 在 r2v 词缀上的优先级与精确性。"""

    def test_r2v_lowercase_match(self) -> None:
        assert (
            _dashscope_video_mode("happyhorse-1.0-r2v", has_image_refs=True)
            == "r2v"
        )

    def test_r2v_uppercase_match(self) -> None:
        # 大小写不敏感：模型名称在判定前会被 lower()
        assert (
            _dashscope_video_mode("Happyhorse-1.0-R2V", has_image_refs=True)
            == "r2v"
        )

    def test_ref2video_does_not_match_r2v(self) -> None:
        # 关键反例：ref2video 必须仍然走 ref_video 分支，不能被新 r2v 检测吞掉。
        assert (
            _dashscope_video_mode("ref2video-some-thing", has_image_refs=True)
            == "ref_video"
        )

    def test_i2v_does_not_match_r2v(self) -> None:
        # happyhorse-1.0-i2v 不能被 r2v 误抓
        assert (
            _dashscope_video_mode("happyhorse-1.0-i2v", has_image_refs=True)
            == "i2v"
        )

    def test_t2v_default(self) -> None:
        assert (
            _dashscope_video_mode("happyhorse-1.0-t2v", has_image_refs=False)
            == "t2v"
        )

    def test_empty_model_returns_t2v(self) -> None:
        assert _dashscope_video_mode(None, has_image_refs=False) == "t2v"


class TestDashscopeR2VBodyShape:
    """``_build_dashscope_video_body`` 在 r2v 模式下的 input.media 形状契约。"""

    @staticmethod
    def _make_input(
        *,
        prompt: str | None = None,
        reference_images_base64: list[str] | None = None,
        model: str = "happyhorse-1.0-r2v",
    ) -> VideoGenerationInput:
        return VideoGenerationInput.model_validate(
            {
                "prompt": prompt,
                "reference_images_base64": reference_images_base64,
                "model": model,
                "ratio": "9:16",
                "seconds": 5,
            }
        )

    def test_r2v_body_with_3_refs(self) -> None:
        refs = ["AAAA", "BBBB", "CCCC"]
        body = _build_dashscope_video_body(
            self._make_input(prompt="一个商品镜头", reference_images_base64=refs)
        )
        media = body["input"]["media"]
        assert len(media) == 3
        assert all(item["type"] == "reference_image" for item in media)
        assert all(item["url"].startswith("data:image/") for item in media)
        assert body["input"]["prompt"] == "一个商品镜头"
        assert body["model"] == "happyhorse-1.0-r2v"

    def test_r2v_body_with_only_prompt_falls_back_to_t2v_silently(self) -> None:
        # contract validator 允许 prompt-only；body 构建不得抛错，仅不附带 media。
        body = _build_dashscope_video_body(
            self._make_input(prompt="hello", reference_images_base64=None)
        )
        assert "media" not in body["input"]
        assert body["input"]["prompt"] == "hello"

    def test_r2v_body_with_empty_list_falls_back_silently(self) -> None:
        # reference_images_base64=[] 等价于缺失，需要 prompt 兜底
        body = _build_dashscope_video_body(
            self._make_input(prompt="hi", reference_images_base64=[])
        )
        assert "media" not in body["input"]

    def test_r2v_body_with_10_refs_raises(self) -> None:
        refs = [f"REF{i}" for i in range(10)]
        with pytest.raises(RuntimeError, match=r"最多支持 9 张"):
            _build_dashscope_video_body(
                self._make_input(prompt="x", reference_images_base64=refs)
            )

    def test_r2v_body_with_data_urls_unchanged(self) -> None:
        # 调用方已传 data URL 时不得被双重包装
        url = "data:image/png;base64,AAAA"
        body = _build_dashscope_video_body(
            self._make_input(prompt="x", reference_images_base64=[url])
        )
        assert body["input"]["media"][0]["url"] == url

    def test_r2v_body_skips_whitespace_only_refs(self) -> None:
        # 全空白与空字符串视为缺失；与 contract validator 中 _strip_optional_b64 对齐
        refs = ["AAAA", "   ", "", "BBBB"]
        body = _build_dashscope_video_body(
            self._make_input(prompt="x", reference_images_base64=refs)
        )
        media = body["input"]["media"]
        assert len(media) == 2
        assert all(item["type"] == "reference_image" for item in media)

    def test_r2v_body_with_9_refs_is_max_allowed(self) -> None:
        # 上限 9 张恰好通过，与 aliyun VideoModelCapability.max_reference_images 对齐
        refs = [f"REF{i}" for i in range(9)]
        body = _build_dashscope_video_body(
            self._make_input(prompt="x", reference_images_base64=refs)
        )
        assert len(body["input"]["media"]) == 9
