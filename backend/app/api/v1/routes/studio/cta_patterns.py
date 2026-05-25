"""CtaPattern 只读接口（W14-T4，P2 CTA 选择器）。

仅暴露列表与详情两个 GET 路径：

- ``GET /api/v1/studio/cta-patterns``：按 ``hardness`` / ``urgency_type``
  双轴过滤系统级 CTA 注册表，``sort_order`` 升序。
- ``GET /api/v1/studio/cta-patterns/{id}``：按 ID 取详情；不存在 →
  404。

写入路径不开放给 API：种子数据由
:func:`app.services.commerce.builtin_cta_patterns.bootstrap_builtin_cta_patterns`
在启动期幂等加载，避免运营误改。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.commerce.patterns import CtaPatternRead
from app.schemas.common import ApiResponse, success_response
from app.services.commerce.pattern_library import PatternLibraryService

router = APIRouter()


@router.get(
    "",
    response_model=ApiResponse[list[CtaPatternRead]],
    summary="CTA 模式列表（按 hardness × urgency_type 过滤，sort_order 升序）",
)
async def list_cta_patterns(
    db: AsyncSession = Depends(get_db),
    hardness: str | None = Query(
        None,
        description="过滤硬度（soft / medium / hard）",
    ),
    urgency_type: str | None = Query(
        None,
        description=(
            "过滤驱动类型（scarcity / urgency / social_proof / benefit / "
            "risk_removal）"
        ),
    ),
) -> ApiResponse[list[CtaPatternRead]]:
    """列出所有系统级 CTA 模式（不分页，规模 ≤5 条）。"""
    service = PatternLibraryService(db)
    items = await service.list_cta_patterns(
        hardness=hardness,
        urgency_type=urgency_type,
    )
    return success_response([CtaPatternRead.model_validate(item) for item in items])


@router.get(
    "/{pattern_id}",
    response_model=ApiResponse[CtaPatternRead],
    summary="CTA 模式详情",
)
async def get_cta_pattern(
    pattern_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CtaPatternRead]:
    """按 ID 获取 CTA 详情，不存在返回 404。"""
    service = PatternLibraryService(db)
    item = await service.get_cta_pattern(pattern_id)
    return success_response(CtaPatternRead.model_validate(item))
