"""阿里百炼视频能力分发与 happyhorse 模型覆盖回归测试（P3 W16）。

覆盖范围：
- resolve_video_capability 对 aliyun_bailian + happyhorse-* 的解析
- VideoModelCapability 新增字段（max_reference_images / supports_r2v / supported_reference_modes）
- aliyun_bailian 自定义注册 / 清空覆盖的回退行为
"""

from __future__ import annotations

import importlib

import pytest

from app.core.integrations import video_capabilities as core_caps
from app.core.integrations.aliyun import video_capabilities as aliyun_caps
from app.core.integrations.video_capabilities import (
    VideoModelCapability,
    clear_video_model_capability_overrides,
    register_video_model_capability,
    resolve_video_capability,
)


@pytest.fixture(autouse=True)
def _restore_aliyun_overrides():
    """每条用例运行后恢复 happyhorse 三件套的内置覆盖，避免污染相邻用例。"""
    yield
    importlib.reload(aliyun_caps)
    # core_caps 的 dispatcher 通过函数内 import 取得 aliyun_caps，因此 reload 即可生效。
    _ = core_caps  # 显式引用以避免 lint 误报。


def test_resolve_happyhorse_r2v_capability():
    """happyhorse-1.0-r2v: 多图参考一体化合成模式（max=9, supports_r2v=True）。"""
    cap = resolve_video_capability(provider="aliyun_bailian", model="happyhorse-1.0-r2v")
    assert cap.max_reference_images == 9
    assert cap.supports_r2v is True
    assert cap.supported_reference_modes == ("multi_ref",)


def test_resolve_happyhorse_i2v_capability():
    """happyhorse-1.0-i2v: 单图参考（max=1），不开启 R2V，多种 mode 可选。"""
    cap = resolve_video_capability(provider="aliyun_bailian", model="happyhorse-1.0-i2v")
    assert cap.max_reference_images == 1
    assert cap.supports_r2v is False
    assert "first" in cap.supported_reference_modes
    assert "first_last_key" in cap.supported_reference_modes


def test_resolve_happyhorse_t2v_capability():
    """happyhorse-1.0-t2v: 纯文本 → 视频，不接收任何参考图。"""
    cap = resolve_video_capability(provider="aliyun_bailian", model="happyhorse-1.0-t2v")
    assert cap.max_reference_images == 0
    assert cap.supports_r2v is False
    assert cap.supported_reference_modes == ("text_only",)


def test_resolve_aliyun_default_when_model_none():
    """未提供 model 时返回 aliyun_bailian 默认能力，三个新字段为安全默认值。"""
    cap = resolve_video_capability(provider="aliyun_bailian", model=None)
    assert cap.max_reference_images == 0
    assert cap.supports_r2v is False
    assert cap.supported_reference_modes == ()
    assert cap.default_ratio == "16:9"


def test_register_custom_aliyun_prefix_round_trip():
    """通过统一入口为 aliyun_bailian 注册自定义前缀覆盖，应能被 resolve 正确返回。"""
    custom = VideoModelCapability(
        supports_seed=False,
        supports_watermark=False,
        max_reference_images=3,
        supports_r2v=True,
        supported_reference_modes=("custom_mode",),
    )
    register_video_model_capability(
        provider="aliyun_bailian",
        model_prefix="custom-x",
        capability=custom,
    )
    try:
        cap = resolve_video_capability(provider="aliyun_bailian", model="custom-x-1.0")
        assert cap.supports_seed is False
        assert cap.max_reference_images == 3
        assert cap.supports_r2v is True
        assert cap.supported_reference_modes == ("custom_mode",)
    finally:
        clear_video_model_capability_overrides(provider="aliyun_bailian")


def test_clear_aliyun_overrides_drops_bootstrap_until_reload():
    """清空 aliyun_bailian 覆盖会移除内置 happyhorse 注册，重新 reload 模块后恢复。"""
    # 清空后 happyhorse-1.0-r2v 应回落至默认能力（max=0）。
    clear_video_model_capability_overrides(provider="aliyun_bailian")
    cap_after_clear = resolve_video_capability(
        provider="aliyun_bailian",
        model="happyhorse-1.0-r2v",
    )
    assert cap_after_clear.max_reference_images == 0
    assert cap_after_clear.supports_r2v is False

    # 重新 import 阿里模块即可重新注册 happyhorse 三件套。
    importlib.reload(aliyun_caps)
    cap_after_reload = resolve_video_capability(
        provider="aliyun_bailian",
        model="happyhorse-1.0-r2v",
    )
    assert cap_after_reload.max_reference_images == 9
    assert cap_after_reload.supports_r2v is True


def test_clear_all_providers_also_clears_aliyun():
    """clear_video_model_capability_overrides() 不带 provider 时应清空 aliyun_bailian 覆盖。"""
    clear_video_model_capability_overrides()
    cap = resolve_video_capability(provider="aliyun_bailian", model="happyhorse-1.0-r2v")
    assert cap.max_reference_images == 0
    assert cap.supports_r2v is False
