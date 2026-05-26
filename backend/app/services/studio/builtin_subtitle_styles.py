"""系统级字幕样式 seed（P3 W18 引入）。

为什么存在：
    P3 W18 起字幕渲染链路统一走 ``SubtitleStyle`` 抽象，前端字幕样式选择器
    与后端 ``shot_subtitle_render`` worker 都依赖一份"系统默认可用"的内置
    样式清单。该清单不应依赖人工 SQL，而要随应用启动自动到位（与
    ``builtin_voice_packs`` 风格保持一致）。

做什么：
    ``bootstrap_builtin_subtitle_styles(db)`` 在应用启动时被调用：
      * 写入 3 个内置平台样式（DOUYIN_DEFAULT / TIKTOK_VIRAL / REELS_LOWER_THIRD）；
      * 幂等：以主键 ``id`` 定位，不存在则 INSERT，存在但有差异则
        UPDATE 名称 / 字体 / 字号 / 颜色 / 边距等可变字段，相同则跳过；
      * 全部标记 ``is_system=True``，业务侧不允许删除；
      * ``sort_order`` 按平台分组递增（DOUYIN 0、TIKTOK 10、REELS 20）。

幂等性契约（与 builtin_voice_packs 同形）：
    SELECT id WHERE id=spec.id
        if exists & 全字段一致 -> "unchanged"
        if exists & 任一字段不同 -> "updated"（覆盖回 spec）
        else -> "inserted"

调用方：``app.bootstrap.bootstrap_async_state``（FastAPI lifespan 内）。

请勿手工修改本文件中样式的 ``id`` 与 ``format``：
    它们与前端字幕样式选择器、shot_subtitle_render worker 的产物路径
    共同消费，错值会导致前端 UI 失效或文件后缀不匹配。

颜色/字号/边距的设计依据见 W18 librarian 调研报告：
    * DOUYIN：思源黑体 Heavy 64px / 黑描边白字 + 青色预高亮 / 底距 200px；
    * TIKTOK：Arial Black 84px / 金黄高亮（白预高亮，\\kf 渐变到金）/ 底距 400px；
    * REELS：Inter 52px / 黑描边白字（无 karaoke）/ 底距 360px 避算法 UI。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subtitle import SubtitleStyle
from app.models.types import SubtitleAlignment, SubtitleFormat


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _BuiltinSubtitleStyleSpec:
    """单个内置字幕样式定义（不可变）。

    字段含义：
        id: 数据库主键；命名约定 ``<platform>_<variant>``。
        name: UI 展示名；中文短名，前端样式选择器直接显示。
        description: 用户可见的简要说明，含适用平台与视觉特点。
        sort_order: 排序权重，越小越靠前；DOUYIN 0、TIKTOK 10、REELS 20。
        font_family: 主字体 family name；务必与 fc-list 输出一致。
        font_fallback_chain: 字体回退链 list[str]；libass 无 CSS 风格 fallback，
            此字段供 jellyfish 服务侧在渲染前按系统已安装字体逐项探测。
        font_size: 字号（脚本像素，按 PlayResY=1920 计）。
        primary_colour / secondary_colour / outline_colour / back_colour:
            ASS 样式颜色字段，统一 ``&HAABBGGRR`` 字符串。
        bold / italic / border_style / outline / shadow / alignment:
            ASS 同名字段语义化封装。
        margin_l / margin_r / margin_v: 边距像素。
        play_res_x / play_res_y: ASS PlayResX/Y。
    """

    id: str
    name: str
    description: str
    sort_order: int
    font_family: str
    font_size: int
    primary_colour: str
    secondary_colour: str
    outline_colour: str
    back_colour: str
    outline: float
    shadow: float
    margin_v: int
    bold: bool = True
    italic: bool = False
    border_style: int = 1
    alignment: SubtitleAlignment = SubtitleAlignment.bottom_center
    margin_l: int = 60
    margin_r: int = 60
    play_res_x: int = 1080
    play_res_y: int = 1920
    language_code: str = "zh-CN"
    format: SubtitleFormat = SubtitleFormat.ass
    font_fallback_chain: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# 注册表（3 个内置样式，顺序即 sort_order 顺序）
# ---------------------------------------------------------------------------


_BUILTIN: Final[list[_BuiltinSubtitleStyleSpec]] = [
    _BuiltinSubtitleStyleSpec(
        id="douyin_default",
        name="抖音默认",
        description=(
            "抖音 9:16 主流字幕样式：思源黑体 Heavy 64px，白字青色预高亮 + 黑描边 + "
            "50% 黑阴影，底距 200px 留出抖音底部 UI 安全区。"
        ),
        sort_order=0,
        font_family="Source Han Sans CN Heavy",
        font_fallback_chain=(
            "Source Han Sans CN Heavy",
            "Source Han Sans CN",
            "PingFang SC",
            "Noto Sans CJK SC",
            "Arial",
        ),
        font_size=64,
        primary_colour="&H00FFFFFF",
        secondary_colour="&H00FFFF00",
        outline_colour="&H00000000",
        back_colour="&H80000000",
        outline=3.0,
        shadow=1.0,
        margin_v=200,
    ),
    _BuiltinSubtitleStyleSpec(
        id="tiktok_viral",
        name="TikTok 病毒式",
        description=(
            "TikTok 流行字幕样式：Arial Black 84px，金黄高亮（白预高亮 \\kf 渐变到金）+ "
            "黑粗描边 6px + 25% 黑阴影，居中下底距 400px，配合逐词高亮节奏感强。"
        ),
        sort_order=10,
        font_family="Arial Black",
        font_fallback_chain=(
            "Arial Black",
            "Impact",
            "Anton",
            "Bebas Neue",
            "Arial",
        ),
        font_size=84,
        primary_colour="&H0000D7FF",
        secondary_colour="&H00FFFFFF",
        outline_colour="&H00000000",
        back_colour="&H40000000",
        outline=6.0,
        shadow=2.0,
        margin_v=400,
        language_code="en-US",
    ),
    _BuiltinSubtitleStyleSpec(
        id="reels_lower_third",
        name="Reels 下三分之一",
        description=(
            "Instagram Reels 下三分之一字幕：Inter 52px，黑描边白字 + 75% 黑阴影，"
            "底距 360px 避开 Reels 算法 UI（caption + audio + CTA + 引擎按钮）。"
        ),
        sort_order=20,
        font_family="Inter",
        font_fallback_chain=(
            "Inter",
            "Montserrat",
            "SF Pro Display",
            "Helvetica Neue",
            "Arial",
        ),
        font_size=52,
        primary_colour="&H00FFFFFF",
        secondary_colour="&H00FFFFFF",
        outline_colour="&H00000000",
        back_colour="&HC0000000",
        outline=4.0,
        shadow=2.0,
        margin_v=360,
        margin_l=90,
        margin_r=90,
        language_code="en-US",
    ),
]


# ---------------------------------------------------------------------------
# 启动函数
# ---------------------------------------------------------------------------


async def bootstrap_builtin_subtitle_styles(db: AsyncSession) -> dict[str, int]:
    """启动时调用，幂等地确保 3 个系统级字幕样式存在并保持 canonical。

    幂等策略（与 builtin_voice_packs 完全一致）：
        以主键 ``id`` 查询已有记录：
            * 命中 + 字段全部一致 -> ``unchanged`` 计数；
            * 命中 + 任一字段不同 -> ``updated`` 计数（覆盖回 spec）；
              注意：``format`` / ``language_code`` 视为不变量，本函数不会
              去"修复"它们——如果出现不一致，说明业务在用同一个 ``id``
              复用记录，应在上游修复，而不是默默改写；
            * 未命中 -> ``inserted`` 计数（按 spec 新插入）。

    用户自定义样式（``is_system=False``）不在本函数管辖范围内：
        seed 只负责系统行；用户复制 / 修改的样式生命周期由前端 + 业务
        service 单独管理。

    Args:
        db: 已绑定到目标库的 AsyncSession；本函数只对 ``subtitle_styles``
            表做读 / 写，并在最后一次性 ``commit()``。

    Returns:
        ``{"inserted": N, "updated": M, "unchanged": K}`` 计数字典，
        与 ``bootstrap_builtin_voice_packs`` 同形契约。
    """

    inserted = 0
    updated = 0
    unchanged = 0

    for spec in _BUILTIN:
        existing = await db.get(SubtitleStyle, spec.id)
        if existing is None:
            db.add(
                SubtitleStyle(
                    id=spec.id,
                    name=spec.name,
                    description=spec.description,
                    language_code=spec.language_code,
                    format=spec.format,
                    font_family=spec.font_family,
                    font_fallback_chain=list(spec.font_fallback_chain),
                    font_size=spec.font_size,
                    primary_colour=spec.primary_colour,
                    secondary_colour=spec.secondary_colour,
                    outline_colour=spec.outline_colour,
                    back_colour=spec.back_colour,
                    bold=spec.bold,
                    italic=spec.italic,
                    border_style=spec.border_style,
                    outline=spec.outline,
                    shadow=spec.shadow,
                    alignment=spec.alignment,
                    margin_l=spec.margin_l,
                    margin_r=spec.margin_r,
                    margin_v=spec.margin_v,
                    play_res_x=spec.play_res_x,
                    play_res_y=spec.play_res_y,
                    is_system=True,
                    sort_order=spec.sort_order,
                )
            )
            inserted += 1
            continue

        if _is_same(existing, spec):
            unchanged += 1
            continue

        _apply_spec(existing, spec)
        updated += 1

    await db.commit()
    return {"inserted": inserted, "updated": updated, "unchanged": unchanged}


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _is_same(record: SubtitleStyle, spec: _BuiltinSubtitleStyleSpec) -> bool:
    """比较 DB 行与 spec 是否完全一致；用于决定 unchanged vs updated。

    可变字段：``name`` / ``description`` / ``font_family`` /
    ``font_fallback_chain`` / ``font_size`` / 颜色四件套 / ``bold`` /
    ``italic`` / ``border_style`` / ``outline`` / ``shadow`` / ``alignment`` /
    边距三件套 / ``play_res_x`` / ``play_res_y`` / ``sort_order``。

    ``format`` / ``language_code`` / ``is_system`` 视为不变量，不参与幂等比较。
    """

    return (
        record.name == spec.name
        and record.description == spec.description
        and record.font_family == spec.font_family
        and list(record.font_fallback_chain or []) == list(spec.font_fallback_chain)
        and record.font_size == spec.font_size
        and record.primary_colour == spec.primary_colour
        and record.secondary_colour == spec.secondary_colour
        and record.outline_colour == spec.outline_colour
        and record.back_colour == spec.back_colour
        and bool(record.bold) == spec.bold
        and bool(record.italic) == spec.italic
        and record.border_style == spec.border_style
        and float(record.outline) == spec.outline
        and float(record.shadow) == spec.shadow
        and _alignment_equals(record.alignment, spec.alignment)
        and record.margin_l == spec.margin_l
        and record.margin_r == spec.margin_r
        and record.margin_v == spec.margin_v
        and record.play_res_x == spec.play_res_x
        and record.play_res_y == spec.play_res_y
        and record.sort_order == spec.sort_order
    )


def _apply_spec(record: SubtitleStyle, spec: _BuiltinSubtitleStyleSpec) -> None:
    """把 spec 的可变字段同步到一行 ORM 记录上。

    见 ``_is_same`` 注释：本函数不修改 ``format`` / ``language_code`` 等
    不变量，避免误修复上游异常。
    """

    record.name = spec.name
    record.description = spec.description
    record.font_family = spec.font_family
    record.font_fallback_chain = list(spec.font_fallback_chain)
    record.font_size = spec.font_size
    record.primary_colour = spec.primary_colour
    record.secondary_colour = spec.secondary_colour
    record.outline_colour = spec.outline_colour
    record.back_colour = spec.back_colour
    record.bold = spec.bold
    record.italic = spec.italic
    record.border_style = spec.border_style
    record.outline = spec.outline
    record.shadow = spec.shadow
    record.alignment = spec.alignment
    record.margin_l = spec.margin_l
    record.margin_r = spec.margin_r
    record.margin_v = spec.margin_v
    record.play_res_x = spec.play_res_x
    record.play_res_y = spec.play_res_y
    record.sort_order = spec.sort_order


def _alignment_equals(left: object, right: SubtitleAlignment) -> bool:
    """容忍 SQLAlchemy 不同后端对 Enum 列返回的 str / Enum 差异。

    SQLite 把 Enum 列以原始字符串返回，MySQL 在 ``native_enum=True``
    下返回 Enum 实例；统一比较 ``.value`` 即可（与
    ``builtin_voice_packs._gender_equals`` 同形）。
    """

    if isinstance(left, SubtitleAlignment):
        return left == right
    return str(left) == right.value


__all__ = [
    "bootstrap_builtin_subtitle_styles",
]
