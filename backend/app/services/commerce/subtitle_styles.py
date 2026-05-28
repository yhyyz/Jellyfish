"""字幕样式 service（W20-T0b 列表 + W30-T3 项目级 CRUD）。

职责边界（与 ``AGENTS.md`` 第 4 条保持一致）：

- 路由层只负责收参、依赖注入、调用 service、包装 ``ApiResponse``。
- 本 service 层负责：
  * 业务逻辑（按系统级 / 文件格式 / 项目级覆盖过滤的 SELECT 编排）
  * 排序约定（``is_system DESC`` + ``sort_order`` + ``name`` 三层稳定排序）
  * ``alignment`` ASS numpad 整数化（ORM 的 ``SubtitleAlignment`` 字符串
    枚举 → ASS Style 行 1-9 numpad int），让前端字幕预览组件直接消费
  * W30 项目级 CRUD：``(project_id, name)`` 唯一性 enforce、系统级行
    immutable 校验、merged 视图（同名项目级覆盖系统级）

为什么把 alignment 数值映射放在 service 而不是 schema：
    pydantic ``BaseModel.model_validate`` 走 ``from_attributes`` 路径时
    会按字段名直接读取 ORM 属性，``SubtitleAlignment`` 枚举值（``"bottom_center"``）
    与 schema 期望的 ``int`` 类型不一致会触发 ValidationError。把转换收
    敛在 service 层 dict 化时统一处理，保持 schema 字段语义清晰，避免在
    pydantic 校验器里塞业务映射。

W30 项目级 CRUD：
    - 系统级行（``project_id IS NULL``）禁止 POST/PATCH/DELETE，service
      层直接抛 :class:`HTTPException(403)`，与 voice_packs_custom DELETE
      系统行的拒绝路径同源。
    - 同 project 内 ``name`` 唯一；冲突抛 ``HTTPException(409)``。
    - merged 视图：同 project_id 项目级行覆盖系统级同名行；项目级行没有
      对应系统级同名行时也单独列出。
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.studio_projects import Project
from app.models.subtitle import SubtitleStyle
from app.models.types import SubtitleAlignment, SubtitleFormat
from app.schemas.commerce.subtitle_styles import (
    ProjectSubtitleStyleCreateInput,
    ProjectSubtitleStyleUpdateInput,
)


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

_NUMPAD_TO_ALIGNMENT: dict[int, SubtitleAlignment] = {
    v: SubtitleAlignment(k) for k, v in _ALIGNMENT_TO_NUMPAD.items()
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
        "project_id": obj.project_id,
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


# ---------------------------------------------------------------------------
# W30-T3：项目级 CRUD
# ---------------------------------------------------------------------------


async def _ensure_project_exists(db: AsyncSession, project_id: str) -> None:
    """确认 ``project_id`` 在 ``projects`` 表里有对应行；缺失抛 404。

    所有项目级 CRUD 都需要校验 project 存在，避免 FK 约束直接抛 IntegrityError
    被前端拿到 5xx；提前返回 404 让 client 拿到一致的错误语义。
    """

    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project not found: {project_id}",
        )


async def _find_project_style_by_name(
    db: AsyncSession, *, project_id: str, name: str
) -> SubtitleStyle | None:
    """按 ``(project_id, name)`` 唯一性 lookup（service 层 enforce 同 project 内 name 唯一）。"""

    stmt = (
        select(SubtitleStyle)
        .where(SubtitleStyle.project_id == project_id)
        .where(SubtitleStyle.name == name)
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def _payload_to_orm_kwargs(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """把入参 dict 中的 numpad ``alignment`` / ``format`` 转成 ORM 期望类型。

    schema 层把 alignment 规范成 1-9 numpad int；ORM 期望
    :class:`SubtitleAlignment` 字符串枚举。format 走对称转换。
    """

    out = dict(payload)
    if "alignment" in out and out["alignment"] is not None:
        out["alignment"] = _NUMPAD_TO_ALIGNMENT[int(out["alignment"])]
    if "format" in out and out["format"] is not None:
        out["format"] = SubtitleFormat(out["format"])
    return out


async def create_project_subtitle_style(
    db: AsyncSession,
    *,
    project_id: str,
    payload: ProjectSubtitleStyleCreateInput,
) -> dict[str, Any]:
    """创建一条项目级覆盖 SubtitleStyle 行。

    Args:
        db: 当前请求绑定的 ``AsyncSession``。
        project_id: 项目 ID。
        payload: 已校验过的 :class:`ProjectSubtitleStyleCreateInput`。

    Returns:
        ``_serialize_subtitle_style`` 序列化后的 dict。

    Raises:
        HTTPException(404): ``project_id`` 不存在。
        HTTPException(409): 同 project 内 ``name`` 已存在
            （上层 SELECT 命中 / DB UNIQUE IntegrityError 兜底，二选一触发）。

    关键内部逻辑：
        - 服务端 mint ``id``（``substyle_<uuid hex 前 12 位>``），不允许调用方
          传入，避免与系统级 seed ID 冲突或恶意覆盖系统行。
        - ``is_system`` 强制 ``False``，``sort_order`` 默认 0；项目级行不参与
          系统级排序权重。
        - ``project_id`` 写入服务端从 path 参数取的值，不接受 body 篡改。
        - 在 ``db.flush()`` 处 catch ``IntegrityError``：alembic 0022 在
          ``(_scope_key, name)`` 上加了 UNIQUE 索引，并发 POST 同 name 时
          后到者会被 DB 直接拒绝，service 层把它统一转换为 HTTP 409，与上
          层 ``SELECT`` 命中分支返回相同的错误语义。
    """

    await _ensure_project_exists(db, project_id)

    existing = await _find_project_style_by_name(
        db, project_id=project_id, name=payload.name
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"SubtitleStyle name already exists in project {project_id}: "
                f"{payload.name!r}"
            ),
        )

    payload_dict = payload.model_dump()
    style_id = f"substyle_{uuid.uuid4().hex[:12]}"
    style = SubtitleStyle(
        id=style_id,
        is_system=False,
        sort_order=0,
        project_id=project_id,
        **_payload_to_orm_kwargs(payload_dict),
    )
    db.add(style)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"SubtitleStyle name already exists in project {project_id}: "
                f"{payload.name!r}"
            ),
        ) from exc
    await db.refresh(style)
    return _serialize_subtitle_style(style)


async def update_project_subtitle_style(
    db: AsyncSession,
    *,
    project_id: str,
    style_id: str,
    payload: ProjectSubtitleStyleUpdateInput,
) -> dict[str, Any]:
    """更新一条项目级覆盖 SubtitleStyle 行。

    Args:
        db: 当前请求绑定的 ``AsyncSession``。
        project_id: 项目 ID（path 参数）。
        style_id: 字幕样式 ID（path 参数）。
        payload: 已校验过的 :class:`ProjectSubtitleStyleUpdateInput`。

    Raises:
        HTTPException(403): 目标行属于系统级（``project_id IS NULL``），immutable。
        HTTPException(404): 行不存在 / 行不属于该 project。
        HTTPException(409): rename 后与同 project 内已有 name 冲突。

    关键内部逻辑：
        - service 层 enforce 行归属：style.project_id 必须等于 path 上的
          project_id；不允许跨 project 写入。
        - 仅更新 ``model_dump(exclude_unset=True)`` 包含的字段，未传字段保留
          原值。
        - 同 name 冲突检测发生在更新前；冲突的是同 project 的另一行。
    """

    await _ensure_project_exists(db, project_id)

    style = await db.get(SubtitleStyle, style_id)
    if style is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SubtitleStyle not found: {style_id}",
        )
    if style.project_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"system SubtitleStyle is immutable: {style_id}",
        )
    if style.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"SubtitleStyle {style_id} does not belong to project "
                f"{project_id}"
            ),
        )

    updates = payload.model_dump(exclude_unset=True)

    new_name = updates.get("name")
    if new_name and new_name != style.name:
        clash = await _find_project_style_by_name(
            db, project_id=project_id, name=new_name
        )
        if clash is not None and clash.id != style.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "SubtitleStyle name already exists in project "
                    f"{project_id}: {new_name!r}"
                ),
            )

    converted = _payload_to_orm_kwargs(updates)
    for field_name, value in converted.items():
        setattr(style, field_name, value)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "SubtitleStyle name already exists in project "
                f"{project_id}: {new_name!r}"
            ),
        ) from exc
    await db.refresh(style)
    return _serialize_subtitle_style(style)


async def delete_project_subtitle_style(
    db: AsyncSession,
    *,
    project_id: str,
    style_id: str,
) -> None:
    """删除一条项目级覆盖 SubtitleStyle 行。

    Args:
        db: 当前请求绑定的 ``AsyncSession``。
        project_id: 项目 ID（path 参数）。
        style_id: 字幕样式 ID（path 参数）。

    Raises:
        HTTPException(403): 目标行属于系统级（``project_id IS NULL``），immutable。
        HTTPException(404): 行不存在 / 行不属于该 project。

    关键内部逻辑：
        - 真删（DELETE FROM）；项目级行没有"软删"语义，删除后 worker
          会自动 fallback 系统级，体现"重置为系统模板"。
        - 已渲染的 SubtitleTrack 仍保留对原 style_id 的 SET NULL 引用（W18
          ORM 已经声明 ``ondelete='SET NULL'``）。
    """

    await _ensure_project_exists(db, project_id)

    style = await db.get(SubtitleStyle, style_id)
    if style is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SubtitleStyle not found: {style_id}",
        )
    if style.project_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"system SubtitleStyle is immutable: {style_id}",
        )
    if style.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"SubtitleStyle {style_id} does not belong to project "
                f"{project_id}"
            ),
        )

    await db.delete(style)
    await db.flush()


async def list_project_subtitle_styles(
    db: AsyncSession,
    *,
    project_id: str,
) -> list[dict[str, Any]]:
    """列出 ``project_id`` 视角下的 merged 字幕样式视图。

    返回顺序与 W20 ``list_subtitle_styles`` 一致：
        - 系统级行（``project_id IS NULL``）置前；
        - ``sort_order`` ASC；
        - ``name`` ASC。

    merged 语义：
        - 若 project 已经针对系统级 ``name`` 建立同名覆盖行，仅返回项目级行
          （隐藏被覆盖的系统级行）；
        - 项目级独有的 name（系统级没有同名 seed）单独列出，``is_system=False``。
    """

    await _ensure_project_exists(db, project_id)

    project_stmt = select(SubtitleStyle).where(
        SubtitleStyle.project_id == project_id
    )
    system_stmt = select(SubtitleStyle).where(
        SubtitleStyle.project_id.is_(None)
    )
    project_rows = (await db.execute(project_stmt)).scalars().all()
    system_rows = (await db.execute(system_stmt)).scalars().all()

    project_names = {row.name for row in project_rows}
    visible_system = [row for row in system_rows if row.name not in project_names]

    merged: list[SubtitleStyle] = list(visible_system) + list(project_rows)
    merged.sort(
        key=lambda row: (
            0 if row.project_id is None else 1,
            row.sort_order,
            row.name,
        )
    )
    return [_serialize_subtitle_style(row) for row in merged]


__all__ = [
    "create_project_subtitle_style",
    "delete_project_subtitle_style",
    "list_project_subtitle_styles",
    "list_subtitle_styles",
    "update_project_subtitle_style",
]
