"""归因聚合查询服务（W22-T3 + W22-T4，P4 Wave B）。

按 4 个维度（公式 / 钩子 / 品牌人格 / 平台）聚合 :class:`StoryOutcome`
指标。SUM 用于绝对量（gmv / 计数）；AVG 用于比率（completion_rate_full）。
维度需要可读 name 时（formula / hook / archetype）LEFT JOIN 注册表，缺失
时回退到 dimension_id 自身，确保数据不会因 join 丢失。

W22-T4 在此之上扩展两条入口：

- :meth:`AnalyticsService.get_kpis`：返回顶部 4 张 KPI 卡片需要的窗口
  汇总（GMV 总量、完播率均值、加购率均值、ROI——见 DESIGN GAP）。
- :meth:`AnalyticsService.list_variant_aggregates`：变体级聚合（按
  variant_id 折叠 outcome）+ 服务端排序 + 分页，10k 量级友好。

DESIGN GAP：``StoryVariant`` 当前没有 ``estimated_cost`` 字段，所以 ROI
无法在后端真实计算。:meth:`AnalyticsService.get_kpis` 永远返回 ``roi=None``，
等待后续单独的 schema 改造刀（不在 W22-T4 范围）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import cast

from sqlalchemy import Float, Integer, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.brand_archetype import BrandArchetype
from app.models.hook_pattern import HookPattern
from app.models.story_formula import StoryFormula, StoryOutcome, StoryVariant
from app.schemas.commerce.analytics import (
    AnalyticsDimension,
    AnalyticsMetric,
    ChartDataPoint,
    KpiRange,
    KpiSummary,
    VariantAggregateRow,
    VariantSortBy,
    VariantSortDir,
)


_RANGE_TO_DAYS: dict[KpiRange, int] = {
    KpiRange.last_7d: 7,
    KpiRange.last_30d: 30,
    KpiRange.last_90d: 90,
}


def _range_cutoff(range_: KpiRange, *, now: datetime | None = None) -> datetime:
    """把 :class:`KpiRange` 翻译成"窗口起点"时间戳。

    Args:
        range_: 查询窗口枚举。
        now: 注入用，便于测试固定时钟；默认 ``datetime.now(timezone.utc)``。

    Returns:
        窗口起点（含 tzinfo=UTC），用于 ``recorded_at >= cutoff`` 过滤。
    """
    anchor = now if now is not None else datetime.now(timezone.utc)
    return anchor - timedelta(days=_RANGE_TO_DAYS[range_])


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

    async def get_kpis(
        self,
        range_: KpiRange,
        *,
        now: datetime | None = None,
    ) -> KpiSummary:
        """汇总顶部 4 张 KPI 卡片需要的窗口指标。

        语义：
        - 时间窗口：``recorded_at >= now - range_days`` （含起点，开右区间不收紧
          原因：业务上下文允许"刚回传的样本"立刻进入今天的统计）。
        - GMV：``SUM(gmv)``，整体相加，与"按 SQL ``SUM(gmv)`` 直接验证"
          口径完全一致（前端 KPI 数字必须 ±0.01 内对得上）。
        - completion_rate_avg：``AVG(completion_rate_full)``，自动忽略 NULL
          行（rate 与 0 语义不同，必须分开）。
        - cart_rate_avg：在 SQL 里用 CASE 把 ``plays = 0`` 的样本剔除后取
          ``AVG(cart_clicks * 1.0 / plays)``；分母 0 的样本若不剔除会导致
          均值错乱（SQLite 会得到 +inf 或 nan）。
        - sample_size：参与聚合的 outcome 行数（非 0 时才返回 GMV 等指标，
          否则一律 None，避免"窗口空集合"被误读为"业务真返回 0"）。

        DESIGN GAP：ROI 永远返回 ``None``。``StoryVariant`` 上没有
        ``estimated_cost`` 字段，前端会展示 "N/A"；待成本字段引入后再补齐
        计算（不在 W22-T4 范围）。

        Args:
            range_: 时间窗口枚举（7d / 30d / 90d）。
            now: 注入参考时间，默认为 UTC ``now``，仅用于测试。

        Returns:
            :class:`KpiSummary` 实例；窗口空集合时数值字段全为 None。
        """
        cutoff = _range_cutoff(range_, now=now)

        plays_for_rate = case(
            (StoryOutcome.plays > 0, StoryOutcome.cart_clicks * 1.0 / StoryOutcome.plays),
            else_=None,
        )

        stmt = select(
            func.coalesce(func.sum(StoryOutcome.gmv), 0).cast(Float).label("gmv_total"),
            func.avg(StoryOutcome.completion_rate_full).label("completion_rate_avg"),
            func.avg(plays_for_rate).label("cart_rate_avg"),
            func.count(StoryOutcome.id).label("sample_size"),
        ).where(StoryOutcome.recorded_at >= cutoff)

        result = await self._db.execute(stmt)
        row = result.one()

        sample_size = int(row.sample_size or 0)
        if sample_size == 0:
            return KpiSummary(
                range=range_,
                gmv_total=None,
                roi=None,
                completion_rate_avg=None,
                cart_rate_avg=None,
                sample_size=0,
            )

        return KpiSummary(
            range=range_,
            gmv_total=float(row.gmv_total) if row.gmv_total is not None else 0.0,
            roi=None,
            completion_rate_avg=(
                float(row.completion_rate_avg) if row.completion_rate_avg is not None else None
            ),
            cart_rate_avg=(
                float(row.cart_rate_avg) if row.cart_rate_avg is not None else None
            ),
            sample_size=sample_size,
        )

    async def list_variant_aggregates(
        self,
        *,
        offset: int = 0,
        limit: int = 20,
        sort_by: VariantSortBy = VariantSortBy.gmv,
        sort_dir: VariantSortDir = VariantSortDir.desc,
        range_: KpiRange | None = None,
        now: datetime | None = None,
    ) -> tuple[list[VariantAggregateRow], int]:
        """变体级聚合 + 服务端分页 + 排序。

        语义：
        - 把每个变体名下的所有 outcome 折叠成一行（``GROUP BY variant_id``）。
        - 数值列：plays / cart_clicks / orders / gmv 走 SUM；
          completion_rate_full 走 AVG（与 KPI 摘要保持口径一致）。
        - cart_rate：``SUM(cart_clicks) / NULLIF(SUM(plays), 0)``，
          总播放为 0 时返回 NULL，前端展示 "N/A"。
        - 没有 outcome 的变体不会出现在列表中（``INNER JOIN``）；和老分析逻辑
          的"维度不出现在归因图"一致。
        - ``range_`` 提供时按 ``recorded_at >= cutoff`` 过滤；不提供时使用
          全部历史 outcome（用于查询单个变体全生命周期）。
        - ``offset`` / ``limit`` 在 SQL 端 LIMIT/OFFSET，10k 量级友好；
          ``total`` 通过 ``COUNT(DISTINCT variant_id)`` 子查询返回。

        Args:
            offset: 跳过前 N 行；负数会被钳制为 0。
            limit: 单页上限；最大 100，超过会被钳制。
            sort_by: 排序字段；与 :class:`VariantSortBy` 严格枚举对应。
            sort_dir: 排序方向；asc / desc。
            range_: 可选的时间窗口；提供时只统计窗口内 outcome。
            now: 注入参考时间（仅用于测试）。

        Returns:
            ``(rows, total)``：当前页数据行 + 总变体数（用于前端分页器）。
        """
        safe_offset = max(0, offset)
        safe_limit = max(1, min(100, limit))

        plays_sum = func.coalesce(func.sum(StoryOutcome.plays), 0).cast(Integer)
        cart_clicks_sum = func.coalesce(func.sum(StoryOutcome.cart_clicks), 0).cast(Integer)
        orders_sum = func.coalesce(func.sum(StoryOutcome.orders), 0).cast(Integer)
        gmv_sum = func.coalesce(func.sum(StoryOutcome.gmv), 0).cast(Float)
        completion_avg = func.avg(StoryOutcome.completion_rate_full)
        cart_rate_expr = case(
            (
                func.sum(StoryOutcome.plays) > 0,
                func.sum(StoryOutcome.cart_clicks) * 1.0 / func.sum(StoryOutcome.plays),
            ),
            else_=None,
        )
        outcome_count = func.count(StoryOutcome.id)
        last_recorded = func.max(StoryOutcome.recorded_at)

        sort_column_map: dict[VariantSortBy, ColumnElement[float]] = {
            VariantSortBy.gmv: gmv_sum,
            VariantSortBy.plays: plays_sum,
            VariantSortBy.cart_clicks: cart_clicks_sum,
            VariantSortBy.orders: orders_sum,
            VariantSortBy.completion_rate_full: completion_avg,
            VariantSortBy.cart_rate: cart_rate_expr,
            VariantSortBy.recorded_at: last_recorded,
        }
        sort_expr = sort_column_map[sort_by]
        sort_expr = sort_expr.desc() if sort_dir is VariantSortDir.desc else sort_expr.asc()

        base = (
            select(
                StoryVariant.id.label("variant_id"),
                StoryVariant.script_full_text.label("script_full_text"),
                StoryVariant.formula_id.label("formula_id"),
                func.coalesce(StoryFormula.name, StoryVariant.formula_id).label("formula_name"),
                StoryVariant.archetype.label("archetype"),
                StoryVariant.is_champion.label("is_champion"),
                plays_sum.label("plays"),
                completion_avg.label("completion_rate_full"),
                cart_clicks_sum.label("cart_clicks"),
                cart_rate_expr.label("cart_rate"),
                orders_sum.label("orders"),
                gmv_sum.label("gmv"),
                outcome_count.label("outcome_count"),
                last_recorded.label("last_recorded_at"),
            )
            .select_from(StoryVariant)
            .join(StoryOutcome, StoryOutcome.variant_id == StoryVariant.id)
            .outerjoin(StoryFormula, StoryFormula.id == StoryVariant.formula_id)
            .group_by(
                StoryVariant.id,
                StoryVariant.script_full_text,
                StoryVariant.formula_id,
                StoryFormula.name,
                StoryVariant.archetype,
                StoryVariant.is_champion,
            )
        )

        if range_ is not None:
            cutoff = _range_cutoff(range_, now=now)
            base = base.where(StoryOutcome.recorded_at >= cutoff)

        ordered_stmt = base.order_by(sort_expr, StoryVariant.id.asc())
        page_stmt = ordered_stmt.limit(safe_limit).offset(safe_offset)
        page_result = await self._db.execute(page_stmt)

        rows: list[VariantAggregateRow] = []
        for row in page_result.all():
            script_text = row.script_full_text or ""
            variant_name = script_text[:32] if script_text else row.variant_id
            rows.append(
                VariantAggregateRow(
                    variant_id=str(row.variant_id),
                    variant_name=str(variant_name),
                    formula_id=str(row.formula_id) if row.formula_id is not None else None,
                    formula_name=(
                        str(row.formula_name) if row.formula_name is not None else None
                    ),
                    archetype=str(row.archetype) if row.archetype is not None else None,
                    is_champion=bool(row.is_champion),
                    plays=int(row.plays or 0),
                    completion_rate_full=(
                        float(row.completion_rate_full)
                        if row.completion_rate_full is not None
                        else None
                    ),
                    cart_clicks=int(row.cart_clicks or 0),
                    cart_rate=(float(row.cart_rate) if row.cart_rate is not None else None),
                    orders=int(row.orders or 0),
                    gmv=float(row.gmv or 0.0),
                    outcome_count=int(row.outcome_count or 0),
                )
            )

        count_stmt = select(func.count(func.distinct(StoryOutcome.variant_id))).select_from(
            StoryOutcome
        )
        if range_ is not None:
            cutoff = _range_cutoff(range_, now=now)
            count_stmt = count_stmt.where(StoryOutcome.recorded_at >= cutoff)
        total = int((await self._db.execute(count_stmt)).scalar_one() or 0)

        return rows, total


__all__ = ["AnalyticsService"]
