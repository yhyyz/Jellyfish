"""阿里百炼视频能力声明与覆盖注册（P3 W16 引入）。

本模块在 import 时自动将 happyhorse-1.0-{t2v,i2v,r2v} 三件套的能力覆盖
预置到 ``_ALIYUN_BAILIAN_MODEL_OVERRIDES``，确保上层调用 ``resolve_video_capability``
时可以直接得到正确的多图参考、reference_mode 等约束。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.integrations.video_capabilities import ALLOWED_RATIOS, VideoModelCapability

if TYPE_CHECKING:
    from app.core.contracts.video_generation import VideoGenerationInput

# 阿里百炼 provider 的兜底能力，未匹配任何前缀时使用。
_ALIYUN_BAILIAN_DEFAULT = VideoModelCapability(
    supports_seed=True,
    supports_watermark=True,
    allowed_ratios=set(ALLOWED_RATIOS),
    default_ratio="16:9",
    max_reference_images=0,
    supports_r2v=False,
    supported_reference_modes=(),
)

# key: 模型前缀（小写），import 时预置 happyhorse 三件套，运行时也可继续注册自定义前缀。
_ALIYUN_BAILIAN_MODEL_OVERRIDES: dict[str, VideoModelCapability] = {
    # 纯文本生成视频：不接收任何参考图，reference_mode 仅允许 text_only。
    "happyhorse-1.0-t2v": VideoModelCapability(
        supports_seed=True,
        supports_watermark=True,
        allowed_ratios=set(ALLOWED_RATIOS),
        default_ratio="16:9",
        max_reference_images=0,
        supports_r2v=False,
        supported_reference_modes=("text_only",),
    ),
    # 单图参考生成视频：仅允许 1 张参考图，支持多种关键帧位置语义。
    "happyhorse-1.0-i2v": VideoModelCapability(
        supports_seed=True,
        supports_watermark=True,
        allowed_ratios=set(ALLOWED_RATIOS),
        default_ratio="16:9",
        max_reference_images=1,
        supports_r2v=False,
        supported_reference_modes=("first", "last", "first_last", "key", "first_last_key"),
    ),
    # 多图参考一体化合成（R2V）：最多 9 张参考图，独有 multi_ref 模式，且不写水印。
    "happyhorse-1.0-r2v": VideoModelCapability(
        supports_seed=True,
        supports_watermark=False,
        allowed_ratios=set(ALLOWED_RATIOS),
        default_ratio="16:9",
        max_reference_images=9,
        supports_r2v=True,
        supported_reference_modes=("multi_ref",),
    ),
}


def register_aliyun_bailian_video_capability(
    *,
    model_prefix: str,
    capability: VideoModelCapability,
) -> None:
    """注册阿里百炼模型前缀的能力覆盖。

    参数：
    - model_prefix: 不区分大小写的模型前缀，前后空白会被剥离，空字符串会直接报错。
    - capability:   该前缀命中后返回的能力对象，由调用侧负责构造。
    """
    prefix = model_prefix.strip().lower()
    if not prefix:
        raise ValueError("model_prefix must not be empty")
    _ALIYUN_BAILIAN_MODEL_OVERRIDES[prefix] = capability


def clear_aliyun_bailian_video_capability_overrides() -> None:
    """清空全部阿里百炼覆盖（包含 import 时预置的 happyhorse 三件套）。

    清空后如需恢复 happyhorse 默认覆盖，应通过 ``importlib.reload`` 重新加载本模块。
    """
    _ALIYUN_BAILIAN_MODEL_OVERRIDES.clear()


def _pick_override(model: str | None) -> VideoModelCapability | None:
    """按最长前缀优先匹配模型覆盖，避免通用前缀压住具体前缀。"""
    if not model:
        return None
    value = model.strip().lower()
    if not value:
        return None
    for prefix, cap in sorted(
        _ALIYUN_BAILIAN_MODEL_OVERRIDES.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if value.startswith(prefix):
            return cap
    return None


def resolve_aliyun_bailian_video_capability(model: str | None) -> VideoModelCapability:
    """解析模型对应的阿里百炼能力，未命中前缀时回落到默认能力。"""
    return _pick_override(model) or _ALIYUN_BAILIAN_DEFAULT


def validate_aliyun_bailian_video_options(input_: VideoGenerationInput) -> None:
    """阿里百炼能力校验入口（避免调用侧传 provider 字面量）。"""
    from app.core.contracts.video_generation import VideoGenerationInput as _VideoGenerationInput
    from app.core.integrations.video_capabilities import validate_video_options

    assert isinstance(input_, _VideoGenerationInput)
    validate_video_options(provider="aliyun_bailian", model=input_.model, input_=input_)
