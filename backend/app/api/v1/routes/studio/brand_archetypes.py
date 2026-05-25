"""BrandArchetype 只读接口（W14-T4，P2 品牌人格原型选择器）。

仅暴露列表与详情两个 GET 路径：

- ``GET /api/v1/studio/brand-archetypes``：列出全部 12 条系统级原型，
  ``sort_order`` 升序。
- ``GET /api/v1/studio/brand-archetypes/{id}``：按 ID 取详情；不存在 →
  404。

写入路径不开放给 API：种子数据由
:func:`app.services.commerce.builtin_brand_archetypes.bootstrap_builtin_brand_archetypes`
在启动期幂等加载，避免运营误改。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.commerce.patterns import BrandArchetypeRead
from app.schemas.common import ApiResponse, success_response
from app.services.commerce.pattern_library import PatternLibraryService

router = APIRouter()


@router.get(
    "",
    response_model=ApiResponse[list[BrandArchetypeRead]],
    summary="品牌人格原型列表（sort_order 升序）",
)
async def list_brand_archetypes(
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[BrandArchetypeRead]]:
    """列出所有系统级品牌人格原型（不分页，规模 ≤12 条）。"""
    service = PatternLibraryService(db)
    items = await service.list_brand_archetypes()
    return success_response(
        [BrandArchetypeRead.model_validate(item) for item in items]
    )


@router.get(
    "/{archetype_id}",
    response_model=ApiResponse[BrandArchetypeRead],
    summary="品牌人格原型详情",
)
async def get_brand_archetype(
    archetype_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[BrandArchetypeRead]:
    """按 ID 获取品牌原型详情，不存在返回 404。"""
    service = PatternLibraryService(db)
    item = await service.get_brand_archetype(archetype_id)
    return success_response(BrandArchetypeRead.model_validate(item))
