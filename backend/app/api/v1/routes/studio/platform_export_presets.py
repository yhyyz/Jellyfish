"""``/api/v1/studio/platform-export-presets/*`` 路由（W23-T1，P4 Wave A）。

5 个端点：

- ``GET    /api/v1/studio/platform-export-presets``
- ``GET    /api/v1/studio/platform-export-presets/{preset_id}``
- ``POST   /api/v1/studio/platform-export-presets``
- ``PATCH  /api/v1/studio/platform-export-presets/{preset_id}``
- ``DELETE /api/v1/studio/platform-export-presets/{preset_id}``

系统级预设保护：
    DELETE 路径在 service 层针对 ``is_system=True`` 的行直接抛 400
    （``System PlatformExportPreset cannot be deleted``）；POST 路径
    在 service 层强制 ``is_system=False``，避免用户伪造系统预设。

路由层只做收参 + 调 service + 包装 ``ApiResponse``，业务逻辑全部下沉
到 :mod:`app.services.commerce.platform_export_presets`。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.common import ApiResponse, created_response, success_response
from app.schemas.studio.platform_export_preset import (
    PlatformExportPresetCreate,
    PlatformExportPresetRead,
    PlatformExportPresetUpdate,
)
from app.services.commerce.platform_export_presets import (
    create_platform_export_preset,
    delete_platform_export_preset,
    get_platform_export_preset,
    list_platform_export_presets,
    update_platform_export_preset,
)

router = APIRouter()


@router.get(
    "",
    response_model=ApiResponse[list[PlatformExportPresetRead]],
    summary="平台导出预设列表（按 platform / is_system 过滤）",
)
async def list_platform_export_presets_endpoint(
    db: AsyncSession = Depends(get_db),
    platform: str | None = Query(
        None,
        description="按平台过滤（douyin / kuaishou / xiaohongshu / youtube / tiktok）",
    ),
    is_system: bool | None = Query(
        None,
        description="是否只列系统级预设；true=仅系统 / false=仅用户自定义 / 缺省=全部",
    ),
) -> ApiResponse[list[PlatformExportPresetRead]]:
    """列出预设。

    路由职责保持瘦身：收参 → 调 service → ``model_validate`` →
    ``success_response``，不在此处做业务过滤或字段映射。
    """

    items = await list_platform_export_presets(
        db,
        platform=platform,
        is_system=is_system,
    )
    return success_response(
        [PlatformExportPresetRead.model_validate(item) for item in items]
    )


@router.get(
    "/{preset_id}",
    response_model=ApiResponse[PlatformExportPresetRead],
    summary="平台导出预设详情",
)
async def get_platform_export_preset_endpoint(
    preset_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PlatformExportPresetRead]:
    """按 ID 获取预设详情；不存在 → 404。"""

    record = await get_platform_export_preset(db, preset_id)
    return success_response(PlatformExportPresetRead.model_validate(record))


@router.post(
    "",
    response_model=ApiResponse[PlatformExportPresetRead],
    status_code=status.HTTP_201_CREATED,
    summary="创建用户态平台导出预设",
)
async def create_platform_export_preset_endpoint(
    body: PlatformExportPresetCreate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PlatformExportPresetRead]:
    """创建用户态预设；``is_system`` 由 service 强制为 False。

    入参 schema 已禁止显式声明 ``is_system``（``extra="forbid"``）；id 缺
    省由 service 生成 uuid4().hex；命中唯一约束 → 409。
    """

    record = await create_platform_export_preset(db, body.model_dump())
    return created_response(PlatformExportPresetRead.model_validate(record))


@router.patch(
    "/{preset_id}",
    response_model=ApiResponse[PlatformExportPresetRead],
    summary="更新平台导出预设（部分字段）",
)
async def update_platform_export_preset_endpoint(
    preset_id: str,
    body: PlatformExportPresetUpdate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PlatformExportPresetRead]:
    """部分更新；仅写入请求中显式提供的字段；``is_system`` 不开放修改。"""

    record = await update_platform_export_preset(
        db,
        preset_id,
        body.model_dump(exclude_unset=True),
    )
    return success_response(PlatformExportPresetRead.model_validate(record))


@router.delete(
    "/{preset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除平台导出预设（系统预设拒绝删除）",
)
async def delete_platform_export_preset_endpoint(
    preset_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """删除预设；命中 ``is_system=True`` 的行直接返回 400。"""

    await delete_platform_export_preset(db, preset_id)


__all__ = ["router"]
