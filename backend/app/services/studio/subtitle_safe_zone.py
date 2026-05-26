"""字幕安全区 lint（P3 W18 T18-6 引入）。

为什么存在：
    抖音 / TikTok / Reels 三平台 9:16 视频底部都有动态 UI（账号名 / 文案 /
    音乐条 / CTA / 引擎按钮），不同年份的算法 UI 高度持续在变。如果字幕样式
    的 ``margin_v`` 太小，字幕会被 UI 遮挡，影响完播率与可读性。

    本模块在 ``shot_subtitle_render`` worker 渲染前对 ``SubtitleStyle`` 与文本
    内容做静态 lint，违规返回 ``warning`` 列表（不阻塞渲染，仅写入任务结果
    供前端面板提示），避免把硬约束写死在样式表里。

做什么：
    ``check_safe_zone(style)`` 输入一行 ``SubtitleStyle`` ORM 对象，返回 list[str]
    告警；空 list 表示安全。覆盖 4 类 lint：

    1. **底部安全边距**：``alignment=bottom_*`` 时 ``margin_v`` 不应小于平台默认下限
       （DOUYIN ≥ 180、TIKTOK ≥ 380、REELS ≥ 350，留 ≥ 1 行字高 buffer）。
    2. **左右安全边距**：``margin_l`` / ``margin_r`` ≥ 60（抖音 5%）或 ≥ 90（Reels 8%）。
    3. **WCAG 对比度**：``primary_colour`` 与 ``outline_colour`` / ``back_colour``
       间至少满足 4.5:1（仅检查"字芯 vs 描边"主对比，因为带描边字幕实际可读性
       由这层主导）。
    4. **字号下限**：9:16 短视频字幕字号在 PlayResY=1920 下应 ≥ 40，否则移动端
       不可读。

设计要点：
    - 仅做静态规则，不依赖渲染器；测试可纯函数验证。
    - 平台判定走 ``id`` 前缀启发式（``douyin_*`` / ``tiktok_*`` / ``reels_*``），
      避免在 SubtitleStyle 表加 ``platform`` 列；用户自定义样式（无前缀）走最宽
      松的"通用 9:16"阈值。
    - 颜色解析容忍 ``&HAABBGGRR`` 与 ``&Hbbggrr&`` 两种形式（ASS Style vs
      override tag）。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.subtitle import SubtitleStyle
from app.models.types import SubtitleAlignment


# ---------------------------------------------------------------------------
# 平台默认安全区下限（来自 W18 librarian 调研：路由通 / Postplanify / Kreatli）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PlatformSafeZone:
    """单平台安全区下限阈值（不可变，默认值参见模块注释）。"""

    name: str
    min_margin_v: int
    min_margin_horiz: int
    min_font_size: int


_PLATFORMS: dict[str, _PlatformSafeZone] = {
    "douyin": _PlatformSafeZone(
        name="抖音",
        min_margin_v=180,
        min_margin_horiz=60,
        min_font_size=48,
    ),
    "tiktok": _PlatformSafeZone(
        name="TikTok",
        min_margin_v=380,
        min_margin_horiz=60,
        min_font_size=56,
    ),
    "reels": _PlatformSafeZone(
        name="Reels",
        min_margin_v=350,
        min_margin_horiz=90,
        min_font_size=44,
    ),
}

#: 通用 9:16 兜底（用户自定义样式无平台前缀时使用）。
_GENERIC: _PlatformSafeZone = _PlatformSafeZone(
    name="通用 9:16",
    min_margin_v=120,
    min_margin_horiz=40,
    min_font_size=40,
)

#: WCAG AA 普通文本要求的最小对比度（4.5:1）。
WCAG_MIN_CONTRAST: float = 4.5


def _resolve_platform(style_id: str) -> _PlatformSafeZone:
    """根据样式 ID 前缀启发式定位平台阈值。

    无匹配时回退到通用 9:16；不区分大小写。
    """

    lower = (style_id or "").strip().lower()
    for prefix, zone in _PLATFORMS.items():
        if lower.startswith(prefix):
            return zone
    return _GENERIC


# ---------------------------------------------------------------------------
# 颜色解析与 WCAG 对比度
# ---------------------------------------------------------------------------


def _parse_ass_colour(value: str) -> tuple[int, int, int] | None:
    """把 ASS 颜色字符串解析为 ``(r, g, b)`` 元组。

    支持两种形式：
    - ``&HAABBGGRR`` (10 字符 + 前缀)：Style 行用，含 alpha；忽略 alpha 字节。
    - ``&Hbbggrr&`` (8 字符 + 前后 ``&``)：override tag 用，无 alpha。

    无法解析时返回 ``None``，让上层选择跳过该项 lint 还是当成不安全。
    """

    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw.upper().startswith("&H"):
        return None
    body = raw[2:].rstrip("&")
    if len(body) == 8:
        # AABBGGRR：跳过 alpha
        body = body[2:]
    if len(body) != 6:
        return None
    try:
        bb = int(body[0:2], 16)
        gg = int(body[2:4], 16)
        rr = int(body[4:6], 16)
    except ValueError:
        return None
    return (rr, gg, bb)


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG 相对亮度计算公式（sRGB → 线性 → 加权）。

    参考：https://www.w3.org/TR/WCAG20/#relativeluminancedef
    """

    def _channel(value: int) -> float:
        srgb = value / 255.0
        return srgb / 12.92 if srgb <= 0.03928 else ((srgb + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def _contrast_ratio(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    """WCAG 对比度（亮 / 暗 + 0.05 公式）。

    参考：https://www.w3.org/TR/WCAG20/#contrast-ratiodef
    """

    l1 = _relative_luminance(fg)
    l2 = _relative_luminance(bg)
    lighter, darker = (l1, l2) if l1 >= l2 else (l2, l1)
    return (lighter + 0.05) / (darker + 0.05)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def check_safe_zone(style: SubtitleStyle) -> list[str]:
    """对单行 ``SubtitleStyle`` 执行静态安全区 lint，返回告警列表。

    告警行为可阻止渲染（由调用方决定），但本函数自身只产出文本，不抛异常。
    空 list 表示样式安全可用。

    Args:
        style: 待 lint 的 SubtitleStyle ORM 对象。

    Returns:
        告警字符串列表，按检查顺序返回；可直接拼到任务 ``result.warnings``。
    """

    warnings: list[str] = []
    zone = _resolve_platform(style.id)

    # 1) 字号下限
    if style.font_size < zone.min_font_size:
        warnings.append(
            f"font_size={style.font_size} 小于 {zone.name} 下限 "
            f"{zone.min_font_size}，移动端可读性可能不足"
        )

    # 2) 底部安全边距（仅 alignment 为 bottom_* 时检查）
    is_bottom = _is_bottom_alignment(style.alignment)
    if is_bottom and style.margin_v < zone.min_margin_v:
        warnings.append(
            f"margin_v={style.margin_v} 小于 {zone.name} 底部 UI 安全下限 "
            f"{zone.min_margin_v}，字幕可能被算法 UI 遮挡"
        )

    # 3) 左右安全边距
    if style.margin_l < zone.min_margin_horiz:
        warnings.append(
            f"margin_l={style.margin_l} 小于 {zone.name} 左侧安全下限 "
            f"{zone.min_margin_horiz}"
        )
    if style.margin_r < zone.min_margin_horiz:
        warnings.append(
            f"margin_r={style.margin_r} 小于 {zone.name} 右侧安全下限 "
            f"{zone.min_margin_horiz}"
        )

    # 4) WCAG 对比度（字芯 vs 描边）
    primary_rgb = _parse_ass_colour(style.primary_colour)
    outline_rgb = _parse_ass_colour(style.outline_colour)
    if primary_rgb is not None and outline_rgb is not None:
        ratio = _contrast_ratio(primary_rgb, outline_rgb)
        if ratio < WCAG_MIN_CONTRAST:
            warnings.append(
                f"primary_colour vs outline_colour 对比度 {ratio:.2f}:1 "
                f"低于 WCAG AA 阈值 {WCAG_MIN_CONTRAST}:1，移动端识读不稳"
            )

    return warnings


def _is_bottom_alignment(alignment: object) -> bool:
    """判断 alignment 是否属于 bottom 行（容忍 SQLAlchemy 返回 str / Enum 差异）。"""

    if isinstance(alignment, SubtitleAlignment):
        value = alignment.value
    else:
        value = str(alignment or "")
    return value.startswith("bottom_")


__all__ = [
    "WCAG_MIN_CONTRAST",
    "check_safe_zone",
]
