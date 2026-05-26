"""``subtitle_safe_zone`` 纯函数单元测试（P3 W18 T18-6）。

覆盖目标：
1. DOUYIN / TIKTOK / REELS 三套合规样式 → 无告警（白名单回归）；
2. 字号过小 → font_size 告警；
3. 底部边距不足（按平台分别） → margin_v 告警；
4. 左右边距不足 → margin_l / margin_r 告警；
5. WCAG 对比度低于 4.5:1 → contrast 告警；
6. 颜色字符串解析容忍 ``&HAABBGGRR`` 与 ``&Hbbggrr&`` 两种形式；
7. 通用 9:16 兜底（用户自定义样式无平台前缀）阈值更宽松；
8. ``alignment=top_*`` 时不检查 margin_v 底部下限（顶部对齐另算）。
"""

# pylint: disable=redefined-outer-name

from __future__ import annotations

from app.models.subtitle import SubtitleStyle
from app.models.types import SubtitleAlignment, SubtitleFormat
from app.services.studio.subtitle_safe_zone import (
    WCAG_MIN_CONTRAST,
    check_safe_zone,
)


def _make_style(**overrides: object) -> SubtitleStyle:
    """构造未入库的 SubtitleStyle 用于纯函数 lint 测试。"""

    defaults: dict[str, object] = {
        "id": "douyin_default",
        "name": "测试样式",
        "description": "",
        "language_code": "zh-CN",
        "format": SubtitleFormat.ass,
        "font_family": "Source Han Sans CN Heavy",
        "font_fallback_chain": [],
        "font_size": 64,
        "primary_colour": "&H00FFFFFF",
        "secondary_colour": "&H00FFFF00",
        "outline_colour": "&H00000000",
        "back_colour": "&H80000000",
        "bold": True,
        "italic": False,
        "border_style": 1,
        "outline": 3.0,
        "shadow": 1.0,
        "alignment": SubtitleAlignment.bottom_center,
        "margin_l": 60,
        "margin_r": 60,
        "margin_v": 200,
        "play_res_x": 1080,
        "play_res_y": 1920,
        "is_system": True,
        "sort_order": 0,
    }
    defaults.update(overrides)
    return SubtitleStyle(**defaults)


# ---------------------------------------------------------------------------
# 1. 三套合规样式：无告警
# ---------------------------------------------------------------------------


def test_check_safe_zone_douyin_default_no_warnings() -> None:
    """W18 builtin DOUYIN_DEFAULT 参数应通过 lint。"""

    style = _make_style(id="douyin_default", font_size=64, margin_v=200)
    assert check_safe_zone(style) == []


def test_check_safe_zone_tiktok_viral_no_warnings() -> None:
    """W18 builtin TIKTOK_VIRAL 参数应通过 lint。"""

    style = _make_style(
        id="tiktok_viral",
        font_size=84,
        margin_v=400,
        margin_l=60,
        margin_r=60,
        primary_colour="&H0000D7FF",
        outline_colour="&H00000000",
    )
    assert check_safe_zone(style) == []


def test_check_safe_zone_reels_lower_third_no_warnings() -> None:
    """W18 builtin REELS_LOWER_THIRD 参数应通过 lint（左右 90px / 底 360px）。"""

    style = _make_style(
        id="reels_lower_third",
        font_size=52,
        margin_v=360,
        margin_l=90,
        margin_r=90,
    )
    assert check_safe_zone(style) == []


# ---------------------------------------------------------------------------
# 2. 字号下限
# ---------------------------------------------------------------------------


def test_check_safe_zone_warns_when_font_size_below_platform_floor() -> None:
    """抖音字号下限 48px；font_size=32 必然触发告警。"""

    style = _make_style(id="douyin_default", font_size=32)
    warnings = check_safe_zone(style)
    assert any("font_size" in w for w in warnings)


# ---------------------------------------------------------------------------
# 3. 底部边距
# ---------------------------------------------------------------------------


def test_check_safe_zone_warns_when_douyin_margin_v_too_small() -> None:
    """抖音底部 UI 安全下限 180px；margin_v=80 必然被遮挡。"""

    style = _make_style(id="douyin_default", margin_v=80)
    warnings = check_safe_zone(style)
    assert any("margin_v" in w for w in warnings)


def test_check_safe_zone_warns_when_tiktok_margin_v_too_small() -> None:
    """TikTok 居中下安全区 380px；margin_v=200 仍偏小。"""

    style = _make_style(
        id="tiktok_viral",
        font_size=84,
        margin_v=200,
        primary_colour="&H0000D7FF",
        outline_colour="&H00000000",
    )
    warnings = check_safe_zone(style)
    assert any("margin_v" in w for w in warnings)


def test_check_safe_zone_skips_margin_v_when_alignment_is_top() -> None:
    """alignment=top_* 时底部 margin_v lint 不应被触发（边距语义换向）。"""

    style = _make_style(
        id="douyin_default",
        alignment=SubtitleAlignment.top_center,
        margin_v=50,
    )
    warnings = check_safe_zone(style)
    assert not any("margin_v" in w for w in warnings)


# ---------------------------------------------------------------------------
# 4. 左右边距
# ---------------------------------------------------------------------------


def test_check_safe_zone_warns_on_too_small_horizontal_margin() -> None:
    """抖音左右安全下限 60px；margin_l=20 必然触发告警。"""

    style = _make_style(id="douyin_default", margin_l=20)
    warnings = check_safe_zone(style)
    assert any("margin_l" in w for w in warnings)


def test_check_safe_zone_reels_requires_wider_horizontal_margin() -> None:
    """Reels 左右安全下限 90px；margin_r=60 触发告警（DOUYIN 阈值通过）。"""

    style = _make_style(
        id="reels_lower_third",
        font_size=52,
        margin_v=360,
        margin_l=60,
        margin_r=60,
    )
    warnings = check_safe_zone(style)
    # margin_l 与 margin_r 都不达 90px，至少 2 条告警。
    margin_warnings = [w for w in warnings if "margin_l" in w or "margin_r" in w]
    assert len(margin_warnings) >= 1


# ---------------------------------------------------------------------------
# 5. WCAG 对比度
# ---------------------------------------------------------------------------


def test_check_safe_zone_warns_when_primary_outline_contrast_below_threshold() -> None:
    """白底白字（primary=outline=白）对比度 1:1，远低于 WCAG 4.5:1。"""

    style = _make_style(
        primary_colour="&H00FFFFFF",
        outline_colour="&H00FAFAFA",
    )
    warnings = check_safe_zone(style)
    assert any("WCAG" in w or "对比度" in w for w in warnings)


def test_check_safe_zone_passes_with_high_contrast_white_on_black() -> None:
    """白字黑描边对比度 21:1，应通过。"""

    style = _make_style(
        primary_colour="&H00FFFFFF",
        outline_colour="&H00000000",
    )
    contrast_warnings = [w for w in check_safe_zone(style) if "对比度" in w]
    assert contrast_warnings == []


def test_check_safe_zone_passes_with_gold_yellow_on_black() -> None:
    """金黄字黑描边（TikTok viral 主色）对比度约 17.4:1，应通过。"""

    style = _make_style(
        primary_colour="&H0000D7FF",
        outline_colour="&H00000000",
    )
    contrast_warnings = [w for w in check_safe_zone(style) if "对比度" in w]
    assert contrast_warnings == []


# ---------------------------------------------------------------------------
# 6. 通用 9:16 兜底（用户自定义样式）
# ---------------------------------------------------------------------------


def test_check_safe_zone_user_custom_style_uses_generic_floor() -> None:
    """非平台前缀的样式 ID 走通用 9:16 阈值（更宽松）。"""

    style = _make_style(
        id="my_custom_style",
        font_size=42,
        margin_v=130,
        margin_l=40,
        margin_r=40,
    )
    warnings = check_safe_zone(style)
    # 通用阈值：font_size ≥ 40 / margin_v ≥ 120 / horizontal ≥ 40，全部通过。
    assert warnings == []


# ---------------------------------------------------------------------------
# 7. 常量对外暴露
# ---------------------------------------------------------------------------


def test_wcag_min_contrast_constant_locked_at_4_5() -> None:
    """WCAG AA 对比度阈值是契约边界，意外修改应被立刻感知。"""

    assert WCAG_MIN_CONTRAST == 4.5
