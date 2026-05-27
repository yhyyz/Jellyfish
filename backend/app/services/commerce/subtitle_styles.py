"""字幕样式只读 service（W20-T0b，P3 W18 配套）。

职责边界（与 ``AGENTS.md`` 第 4 条保持一致）：

- 路由层只负责收参、依赖注入、调用 service、包装 ``ApiResponse``。
- 本 service 层负责：
  * 业务逻辑（按系统级 / 文件格式 / 项目级覆盖过滤的 SELECT 编排）
  * 排序约定（``is_system DESC`` + ``sort_order`` + ``name`` 三层稳定排序）
  * ``alignment`` ASS numpad 整数化（ORM 的 ``SubtitleAlignment`` 字符串
    枚举 → ASS Style 行 1-9 numpad int），让前端字幕预览组件直接消费

为什么把 alignment 数值映射放在 service 而不是 schema：
    pydantic ``BaseModel.model_validate`` 走 ``from_attributes`` 路径时
    会按字段名直接读取 ORM 属性，``SubtitleAlignment`` 枚举值（``"bottom_center"``）
    与 schema 期望的 ``int`` 类型不一致会触发 ValidationError。把转换收
    敛在 service 层 dict 化时统一处理，保持 schema 字段语义清晰，避免在
    pydantic 校验器里塞业务映射。

只读语义：
    本模块只暴露列表查询，不开放 Create/Update/Delete；系统级写入路径
    由 :func:`app.services.studio.builtin_subtitle_styles.bootstrap_builtin_subtitle_styles`
    在启动期幂等管理。``project_id`` 参数为前向兼容预留：当前 ORM 模型
    无 project_id 列（项目级样式覆盖尚未上线），传该参数与不传等价。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subtitle import SubtitleStyle
from app.models.types import SubtitleAlignment


# ASS Style 行 Alignment 字段的 numpad 1-9 映射（与
# :class:`app.models.types.SubtitleAlignment` 行内注释一致）。
# 单独抽常量便于测试断言与未来扩展（例如新增 9-grid 之外的 ass-tags）。
_ALIGNMENT_TO_NUMPAD: dict[str, int] = {
    SubtitleAlignment.bottom_left.value: 1,
    SubtitleAlignment.bottom_center.value: 2,
    SubtitleAlignment.bottom_right.value: 3,
    SubtitleAlignment.middle_left.value: 4,
    SubtitleAlignment.middle_center.value: 5,
    SubtitleAlignment.middle_right.value: 6,
    SubtitleAlignment.top_left.value: 7,
    SubtitleAlignment.top_center.value: 8,
    SubtitleAlignment.top_right.value: 9,
}


def _alignment_to_numpad(alignment: object) -> int:
    """把 :class:`SubtitleAlignment` 枚举或其 ``str`` 值换算为 ASS numpad int。

    Args:
        alignment: 来自 ORM 的 ``SubtitleAlignment`` 枚举值或裸字符串。

    Returns:
        1-9 的整数；未识别值降级为 ``2``（``bottom_center``，短视频默认
        落点），保证前端预览组件总能拿到合法值，不抛 KeyError。
    """

    if isinstance(alignment, SubtitleAlignment):
        key = alignment.value
    else:
        key = str(alignment)
    return _ALIGNMENT_TO_NUMPAD.get(key, 2)


def _serialize_subtitle_style(obj: SubtitleStyle) -> dict[str, Any]:
    """把 :class:`SubtitleStyle` ORM 行展开为 schema-friendly dict。

    Args:
        obj: 单条 ``SubtitleStyle`` ORM 行。

    Returns:
        与 :class:`app.schemas.commerce.subtitle_styles.SubtitleStyleRead`
        字段一一对应的 dict；``alignment`` 已换算为 numpad int，``format``
        / ``language_code`` 等字符串枚举直接透传。
    """

    return {
        "id": obj.id,
        "name": obj.name,
        "description": obj.description,
        "language_code": obj.language_code,
        "format": obj.format.value if hasattr(obj.format, "value") else str(obj.format),
        "font_family": obj.font_family,
        "font_size": obj.font_size,
        "primary_colour": obj.primary_colour,
        "secondary_colour": obj.secondary_colour,
        "outline_colour": obj.outline_colour,
        "back_colour": obj.back_colour,
        "bold": bool(obj.bold),
        "italic": bool(obj.italic),
        "border_style": obj.border_style,
        "outline": obj.outline,
        "shadow": obj.shadow,
        "alignment": _alignment_to_numpad(obj.alignment),
        "margin_l": obj.margin_l,
        "margin_r": obj.margin_r,
        "margin_v": obj.margin_v,
        "play_res_x": obj.play_res_x,
        "play_res_y": obj.play_res_y,
        "font_fallback_chain": list(obj.font_fallback_chain or []),
        "is_system": bool(obj.is_system),
        "sort_order": obj.sort_order,
        "created_at": obj.created_at,
        "updated_at": obj.updated_at,
    }


async def list_subtitle_styles(
    db: AsyncSession,
    *,
    is_system: bool | None = None,
    format: str | None = None,  # noqa: A002 (与 OpenAPI 字段保持一致，故意 shadow 内置)
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """按可选条件列出 ``subtitle_styles`` 表中的全部记录。

    Args:
        db: 当前请求绑定的 ``AsyncSession``，由路由层
            ``Depends(get_db)`` 注入。
        is_system: 可选，``True`` 仅列系统级 seed，``False`` 仅列用户
            自定义；为 ``None`` 时返回全部。
        format: 可选，按字幕文件格式精确过滤（``"ass"`` / ``"srt"`` /
            ``"vtt"``）；为 ``None`` 时不参与过滤。形参借用了内置名
            ``format``，但仅作 SQLAlchemy where 子句的字段语义，不会与
            内置 :func:`format` 冲突（被 ``noqa: A002`` 标注）。
        project_id: 可选，项目级覆盖样式 ID。当前 ORM 模型无 ``project_id``
            列，传该参数与不传等价；保留入参用于前向兼容，避免 W20+
            前端在新增项目级样式 wave 时再走一轮契约改动。

    Returns:
        ``list[dict[str, Any]]``；按 ``is_system DESC`` → ``sort_order ASC``
        → ``name ASC`` 三层稳定排序，确保系统样式永远靠前展示。
        ``alignment`` 字段已换算为 ASS numpad int（1-9）。

    关键内部逻辑：
        与 :func:`list_voice_packs` 风格一致：过滤条件互相独立、AND 关
        系组合；``project_id`` 暂作 no-op 但保留参数，便于 FE 端在切换
        到项目级覆盖样式时不必发版调整 OpenAPI client。
    """

    stmt = select(SubtitleStyle)
    if is_system is not None:
        stmt = stmt.where(SubtitleStyle.is_system == is_system)
    if format is not None:
        stmt = stmt.where(SubtitleStyle.format == format)
    # NOTE: project_id 参数预留：当前 SubtitleStyle ORM 无 project_id 列，
    # 传值不会缩窄结果集；后续上线项目级覆盖样式时在此追加 where 子句。
    _ = project_id  # 显式消费形参，避免 linter 报"未使用"

    stmt = stmt.order_by(
        SubtitleStyle.is_system.desc(),
        SubtitleStyle.sort_order.asc(),
        SubtitleStyle.name.asc(),
    )
    result = await db.execute(stmt)
    return [_serialize_subtitle_style(item) for item in result.scalars().all()]


__all__ = ["list_subtitle_styles"]
