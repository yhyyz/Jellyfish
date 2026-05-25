"""HookPattern 只读接口（W14-T4，P2 钩子选择器）。

仅暴露列表与详情两个 GET 路径：

- ``GET /api/v1/studio/hook-patterns``：按 ``pattern_type`` 检索系统级
  钩子注册表，``sort_order`` 升序。
- ``GET /api/v1/studio/hook-patterns/{id}``：按 ID 取详情；不存在 →
  404。

写入路径不开放给 API：种子数据由
:func:`app.services.commerce.builtin_hook_patterns.bootstrap_builtin_hook_patterns`
在启动期幂等加载，避免运营误改。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.commerce.patterns import HookPatternRead
from app.schemas.common import ApiResponse, success_response
from app.services.commerce.pattern_library import PatternLibraryService

router = APIRouter()


@router.get(
    "",
    response_model=ApiResponse[list[HookPatternRead]],
    summary="钩子模式列表（按 pattern_type 过滤，sort_order 升序）",
)
async def list_hook_patterns(
    db: AsyncSession = Depends(get_db),
    pattern_type: str | None = Query(
        None,
        description="过滤钩子类型（question / conflict / contrast / ...）",
    ),
) -> ApiResponse[list[HookPatternRead]]:
    """列出所有系统级钩子模式（不分页，规模 ≤10 条）。"""
    service = PatternLibraryService(db)
    items = await service.list_hook_patterns(pattern_type=pattern_type)
    return success_response([HookPatternRead.model_validate(item) for item in items])


@router.get(
    "/{pattern_id}",
    response_model=ApiResponse[HookPatternRead],
    summary="钩子模式详情",
)
async def get_hook_pattern(
    pattern_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[HookPatternRead]:
    """按 ID 获取钩子详情，不存在返回 404。"""
    service = PatternLibraryService(db)
    item = await service.get_hook_pattern(pattern_id)
    return success_response(HookPatternRead.model_validate(item))
