"""平台导出预设 CRUD service（W23-T1，P4 Wave A）。

职责边界（与 ``AGENTS.md`` 第 4 条保持一致）：

- 路由层只负责收参、依赖注入、调用 service、包装 ``ApiResponse``。
- 本 service 层负责：
  * 业务逻辑（id 自动生成、name 唯一性校验、平台枚举校验）
  * 状态/数据编排（按平台筛选 + ``is_system DESC`` + ``sort_order ASC``
    + ``name ASC`` 三层稳定排序）
  * 系统预设保护（DELETE 系统预设强制返回 400；PATCH ``is_system`` 字段
    始终被忽略）
  * 错误语义统一（``entity_not_found`` / ``entity_already_exists``）

为什么单独拆 ``platform_export_presets.py`` 而不复用现有 service：
    P4 Wave A 起对该实体开放完整 CRUD（不同于 W17 ``voice_packs`` 的
    只读 service），且系统预设保护逻辑与现有 service 都不重叠，独立成
    一个 service 让后续扩展（例如 W23-T2 渲染管线集成、自定义贴纸校验）
    时不必回头拆分共享类。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform_export_preset import PlatformExportPreset
from app.models.types import Platform
from app.services.common.errors import (
    entity_already_exists,
    entity_not_found,
    invalid_choice,
)


def _coerce_platform(value: str) -> Platform:
    """把请求字符串校验为 :class:`Platform` 枚举。

    无效值统一转换为 400 错误，错误文案走通用 ``invalid_choice`` 模板。
    """

    try:
        return Platform(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=invalid_choice(
                "platform",
                tuple(p.value for p in Platform),
            ),
        ) from exc


async def list_platform_export_presets(
    db: AsyncSession,
    *,
    platform: str | None = None,
    is_system: bool | None = None,
) -> list[PlatformExportPreset]:
    """按可选条件列出 ``platform_export_presets`` 表中的全部记录。

    Args:
        db: 当前请求绑定的 :class:`AsyncSession`，由路由层
            ``Depends(get_db)`` 注入。
        platform: 可选，按平台精确过滤（``douyin`` / ``tiktok`` 等）；
            为 ``None`` 时不参与过滤。
        is_system: 可选，``True`` 仅列系统预设，``False`` 仅列用户自定义；
            为 ``None`` 时返回全部。

    Returns:
        ``list[PlatformExportPreset]`` ORM 行；按 ``is_system DESC`` →
        ``sort_order ASC`` → ``name ASC`` 三层稳定排序，让系统预设永远
        靠前显示，同档位之间按运营预设顺序展示，相同 sort_order 再以
        name 兜底，避免前端选择器抖动。

    关键内部逻辑：
        平台过滤会校验 ``platform`` 入参合法性（无效值返回 400）；
        ``is_system`` 直接当作布尔条件下传，空字符串视作有效值（由调用方
        保证传 ``None`` 而非空串以表达"不过滤"）。
    """

    stmt = select(PlatformExportPreset)
    if platform is not None:
        platform_enum = _coerce_platform(platform)
        stmt = stmt.where(PlatformExportPreset.platform == platform_enum)
    if is_system is not None:
        stmt = stmt.where(PlatformExportPreset.is_system == is_system)
    stmt = stmt.order_by(
        PlatformExportPreset.is_system.desc(),
        PlatformExportPreset.sort_order.asc(),
        PlatformExportPreset.name.asc(),
    )
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)


async def get_platform_export_preset(
    db: AsyncSession,
    preset_id: str,
) -> PlatformExportPreset:
    """按主键查询单条记录；不存在统一抛 404。"""

    record = await db.get(PlatformExportPreset, preset_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=entity_not_found("PlatformExportPreset"),
        )
    return record


async def create_platform_export_preset(
    db: AsyncSession,
    payload: dict[str, Any],
) -> PlatformExportPreset:
    """创建用户态预设（``is_system`` 始终为 False）。

    业务规则：
        * ``id`` 缺省由 service 生成 ``uuid4().hex``，避免前端伪造冲撞
          系统预设的 id；
        * ``platform`` 必须是 :class:`Platform` 合法值（_coerce_platform
          校验）；
        * 命中已存在 ``id`` / ``name`` 唯一约束（DB 主键冲突）→ 409。
    """

    preset_id = payload.get("id") or uuid4().hex
    platform_enum = _coerce_platform(payload["platform"])

    record = PlatformExportPreset(
        id=preset_id,
        name=payload["name"],
        platform=platform_enum,
        aspect_ratio=payload.get("aspect_ratio") or "9:16",
        max_duration_sec=payload["max_duration_sec"],
        subtitle_style_id=payload.get("subtitle_style_id"),
        voice_pack_id=payload.get("voice_pack_id"),
        watermark_file_id=payload.get("watermark_file_id"),
        sticker_specs=list(payload.get("sticker_specs") or []),
        file_format=payload.get("file_format") or "mp4",
        codec_preset=payload.get("codec_preset") or "h264_high_4_1",
        loudness_lufs=float(payload.get("loudness_lufs", -16.0)),
        is_system=False,
        sort_order=int(payload.get("sort_order", 0)),
        description=payload.get("description") or "",
    )
    db.add(record)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=entity_already_exists("PlatformExportPreset"),
        ) from exc
    await db.refresh(record)
    return record


async def update_platform_export_preset(
    db: AsyncSession,
    preset_id: str,
    payload: dict[str, Any],
) -> PlatformExportPreset:
    """部分更新：仅写入 ``payload`` 中显式提供的字段。

    业务规则：
        * 系统预设（``is_system=True``）允许 PATCH（运营层调字段不动
          ``is_system`` 标记）；
        * ``platform`` 提供时必须合法（_coerce_platform 校验）；
        * ``is_system`` 字段在路由层 schema 已被禁止传入；service 层
          做防御式清洗以防绕过。
    """

    record = await get_platform_export_preset(db, preset_id)

    # 防御式：禁止改写 is_system / id（哪怕 schema 漏拦也兜底）
    payload.pop("is_system", None)
    payload.pop("id", None)

    if "platform" in payload and payload["platform"] is not None:
        record.platform = _coerce_platform(payload.pop("platform"))

    for key, value in payload.items():
        if value is None and key in {"name", "aspect_ratio", "file_format", "codec_preset"}:
            # 这些字段在 ORM 上是 NOT NULL，None 视作"不更新"
            continue
        setattr(record, key, value)

    await db.commit()
    await db.refresh(record)
    return record


async def delete_platform_export_preset(
    db: AsyncSession,
    preset_id: str,
) -> None:
    """删除用户预设；系统预设强制返回 400 拒绝。

    系统保护契约：
        * ``is_system=True`` 的行删除请求直接 400，错误文案明确告知运营
          这条数据由 bootstrap 管理；
        * ``is_system=False`` 的行走标准 ``db.delete + commit``，无级联
          外键（其它表都未反向引用 preset.id）。
    """

    record = await get_platform_export_preset(db, preset_id)
    if bool(record.is_system):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="System PlatformExportPreset cannot be deleted",
        )
    await db.delete(record)
    await db.commit()


__all__ = [
    "list_platform_export_presets",
    "get_platform_export_preset",
    "create_platform_export_preset",
    "update_platform_export_preset",
    "delete_platform_export_preset",
]
