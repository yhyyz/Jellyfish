"""``/api/v1/commerce/analytics`` 归因聚合路由（W22-T3，P4 Wave B 2/11）。

四条 endpoint 结构对称（仅维度不同），都接 ``metric`` Query 参数：

* ``GET /commerce/analytics/by-formula?metric=gmv``
* ``GET /commerce/analytics/by-hook?metric=gmv``
* ``GET /commerce/analytics/by-archetype?metric=gmv``
* ``GET /commerce/analytics/by-platform?metric=gmv``

使用 4 个独立 path（而非 ``?dimension=...``）便于 OpenAPI codegen 生成
4 个语义化方法名 + 前端 react-query 独立缓存键。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.commerce.analytics import (
    AnalyticsDimension,
    AnalyticsMetric,
    ChartDataPoint,
    ChartDataResponse,
)
from app.schemas.common import ApiResponse, success_response
from app.services.commerce.analytics_service import AnalyticsService

router = APIRouter()


async def _aggregate(
    db: AsyncSession,
    dimension: AnalyticsDimension,
    metric: AnalyticsMetric,
) -> ChartDataResponse:
    """所有 endpoint 共享的执行逻辑：构 service → 聚合 → 拼壳。"""
    service = AnalyticsService(db)
    points: list[ChartDataPoint] = await service.aggregate(dimension, metric)
    return ChartDataResponse(dimension=dimension, metric=metric, points=points)


@router.get(
    "/analytics/by-formula",
    response_model=ApiResponse[ChartDataResponse],
    summary="按剧情公式归因聚合 outcome 指标",
)
async def get_analytics_by_formula(
    metric: AnalyticsMetric = Query(
        AnalyticsMetric.gmv,
        description="指标：gmv / cart_clicks / completion_rate_full / orders / interactions",
    ),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ChartDataResponse]:
    """按公式 ID 聚合；GMV / 订单 / 加购 / 互动量走 SUM，完播率走 AVG。"""
    payload = await _aggregate(db, AnalyticsDimension.formula, metric)
    return success_response(payload)


@router.get(
    "/analytics/by-hook",
    response_model=ApiResponse[ChartDataResponse],
    summary="按钩子模式归因聚合 outcome 指标",
)
async def get_analytics_by_hook(
    metric: AnalyticsMetric = Query(AnalyticsMetric.gmv, description="指标"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ChartDataResponse]:
    """未指定钩子（``hook_pattern_id IS NULL``）的变体不参与归因。"""
    payload = await _aggregate(db, AnalyticsDimension.hook, metric)
    return success_response(payload)


@router.get(
    "/analytics/by-archetype",
    response_model=ApiResponse[ChartDataResponse],
    summary="按品牌人格归因聚合 outcome 指标",
)
async def get_analytics_by_archetype(
    metric: AnalyticsMetric = Query(AnalyticsMetric.gmv, description="指标"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ChartDataResponse]:
    """``archetype`` 在变体上为可空字段；NULL 行被过滤。"""
    payload = await _aggregate(db, AnalyticsDimension.archetype, metric)
    return success_response(payload)


@router.get(
    "/analytics/by-platform",
    response_model=ApiResponse[ChartDataResponse],
    summary="按投放平台归因聚合 outcome 指标",
)
async def get_analytics_by_platform(
    metric: AnalyticsMetric = Query(AnalyticsMetric.gmv, description="指标"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ChartDataResponse]:
    """``platform`` 直接落在 outcome 上；不需要 join StoryVariant。"""
    payload = await _aggregate(db, AnalyticsDimension.platform, metric)
    return success_response(payload)


__all__ = ["router"]
