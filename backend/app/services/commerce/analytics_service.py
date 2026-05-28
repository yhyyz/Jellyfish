"""归因聚合查询服务（W22-T3，P4 Wave B 2/11）。

按 4 个维度（公式 / 钩子 / 品牌人格 / 平台）聚合 :class:`StoryOutcome`
指标。SUM 用于绝对量（gmv / 计数）；AVG 用于比率（completion_rate_full）。
维度需要可读 name 时（formula / hook / archetype）LEFT JOIN 注册表，缺失
时回退到 dimension_id 自身，确保数据不会因 join 丢失。
"""

from __future__ import annotations

from typing import cast

from sqlalchemy import Float, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.brand_archetype import BrandArchetype
from app.models.hook_pattern import HookPattern
from app.models.story_formula import StoryFormula, StoryOutcome, StoryVariant
from app.schemas.commerce.analytics import (
    AnalyticsDimension,
    AnalyticsMetric,
    ChartDataPoint,
)


class AnalyticsService:
    """归因聚合查询编排。"""

    def __init__(self, db: AsyncSession) -> None:
        """绑定异步会话；单实例对应一次 HTTP 请求。"""
        self._db = db

    @staticmethod
    def _aggregate_for_metric(metric: AnalyticsMetric) -> ColumnElement[float]:
        """按指标返回聚合表达式；rate 走 AVG，其余走 SUM；空集合 → 0。"""
        column_map = {
            AnalyticsMetric.gmv: StoryOutcome.gmv,
            AnalyticsMetric.cart_clicks: StoryOutcome.cart_clicks,
            AnalyticsMetric.completion_rate_full: StoryOutcome.completion_rate_full,
            AnalyticsMetric.orders: StoryOutcome.orders,
            AnalyticsMetric.interactions: StoryOutcome.interactions,
        }
        column = column_map[metric]
        agg = (
            func.avg(column)
            if metric is AnalyticsMetric.completion_rate_full
            else func.sum(column)
        )
        return cast("ColumnElement[float]", func.coalesce(agg, 0).cast(Float))

    async def _aggregate_via_variant(
        self,
        *,
        group_column: ColumnElement[str | None],
        name_join: tuple[type, ColumnElement[bool], ColumnElement[str]] | None,
        metric: AnalyticsMetric,
    ) -> list[ChartDataPoint]:
        """对"经 StoryVariant 中转"的维度（formula / hook / archetype）做聚合。"""
        agg = self._aggregate_for_metric(metric)

        if name_join is None:
            stmt = (
                select(group_column.label("dim_id"), agg.label("metric_value"))
                .select_from(StoryOutcome)
                .join(StoryVariant, StoryOutcome.variant_id == StoryVariant.id)
                .where(group_column.is_not(None))
                .group_by(group_column)
            )
            result = await self._db.execute(stmt)
            return [
                ChartDataPoint(
                    dimension_id=str(row.dim_id),
                    dimension_name=str(row.dim_id),
                    metric_value=float(row.metric_value or 0),
                )
                for row in result.all()
            ]

        name_model, on_clause, name_column = name_join
        stmt = (
            select(
                group_column.label("dim_id"),
                func.coalesce(name_column, group_column).label("dim_name"),
                agg.label("metric_value"),
            )
            .select_from(StoryOutcome)
            .join(StoryVariant, StoryOutcome.variant_id == StoryVariant.id)
            .outerjoin(name_model, on_clause)
            .where(group_column.is_not(None))
            .group_by(group_column, name_column)
        )
        result = await self._db.execute(stmt)
        points = [
            ChartDataPoint(
                dimension_id=str(row.dim_id),
                dimension_name=str(row.dim_name) if row.dim_name is not None else str(row.dim_id),
                metric_value=float(row.metric_value or 0),
            )
            for row in result.all()
        ]
        points.sort(key=lambda p: p.metric_value, reverse=True)
        return points

    async def by_formula(self, metric: AnalyticsMetric) -> list[ChartDataPoint]:
        """按剧情公式聚合：经 StoryVariant.formula_id JOIN StoryFormula.name。"""
        return await self._aggregate_via_variant(
            group_column=StoryVariant.formula_id,
            name_join=(
                StoryFormula,
                StoryVariant.formula_id == StoryFormula.id,
                cast("ColumnElement[str]", StoryFormula.name),
            ),
            metric=metric,
        )

    async def by_hook(self, metric: AnalyticsMetric) -> list[ChartDataPoint]:
        """按钩子模式聚合；NULL hook 行被过滤。"""
        return await self._aggregate_via_variant(
            group_column=StoryVariant.hook_pattern_id,
            name_join=(
                HookPattern,
                StoryVariant.hook_pattern_id == HookPattern.id,
                cast("ColumnElement[str]", HookPattern.name),
            ),
            metric=metric,
        )

    async def by_archetype(self, metric: AnalyticsMetric) -> list[ChartDataPoint]:
        """按品牌人格聚合；archetype 字符串等于 BrandArchetype.id。"""
        return await self._aggregate_via_variant(
            group_column=StoryVariant.archetype,
            name_join=(
                BrandArchetype,
                StoryVariant.archetype == BrandArchetype.id,
                cast("ColumnElement[str]", BrandArchetype.name_zh),
            ),
            metric=metric,
        )

    async def by_platform(self, metric: AnalyticsMetric) -> list[ChartDataPoint]:
        """按投放平台聚合；platform 直接挂在 outcome 上，无需 join。"""
        agg = self._aggregate_for_metric(metric)
        stmt = (
            select(
                StoryOutcome.platform.label("dim_id"),
                agg.label("metric_value"),
            )
            .group_by(StoryOutcome.platform)
        )
        result = await self._db.execute(stmt)
        points = [
            ChartDataPoint(
                dimension_id=str(row.dim_id),
                dimension_name=str(row.dim_id),
                metric_value=float(row.metric_value or 0),
            )
            for row in result.all()
        ]
        points.sort(key=lambda p: p.metric_value, reverse=True)
        return points

    async def aggregate(
        self,
        dimension: AnalyticsDimension,
        metric: AnalyticsMetric,
    ) -> list[ChartDataPoint]:
        """统一派发：按 ``dimension`` 选择对应的 by_xxx 方法。"""
        if dimension is AnalyticsDimension.formula:
            return await self.by_formula(metric)
        if dimension is AnalyticsDimension.hook:
            return await self.by_hook(metric)
        if dimension is AnalyticsDimension.archetype:
            return await self.by_archetype(metric)
        if dimension is AnalyticsDimension.platform:
            return await self.by_platform(metric)
        raise ValueError(f"Unsupported analytics dimension: {dimension}")


__all__ = ["AnalyticsService"]
