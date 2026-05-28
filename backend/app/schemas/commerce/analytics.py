"""投放效果归因聚合 API 的请求/响应模型（W22-T3 + W22-T4，P4 Wave B）。

P4 阶段在 W22-T1 已落地的 ``story_outcomes`` 之上，提供"按维度归因"的
聚合查询入口，给前端 ``/commerce/analytics`` 页面的 4 个图表（按公式 /
钩子 / 品牌人格 / 平台维度）供数。本文件承载所有契约定义：

* :class:`AnalyticsDimension`：可用归因维度的枚举（与路由 path 一一对应）。
* :class:`AnalyticsMetric`：可用指标的枚举（GMV / 加购点击 / 完播率等）。
* :class:`ChartDataPoint`：单个聚合数据点 DTO。
* :class:`ChartDataResponse`：列表响应壳，附带本次查询的 dimension /
  metric 上下文，避免前端把不同维度的缓存混为一谈。

W22-T4 在此之上扩展两类契约，对接 AnalyticsPage 顶部 KPI 卡片 + 变体
对比表：

* :class:`KpiRange` / :class:`KpiSummary`：``GET /kpis`` 的查询窗口枚举
  与摘要响应。``range_*`` 字段统一遵循"窗口口径"，避免前端再二次聚合。
* :class:`VariantSortBy` / :class:`VariantSortDir` / :class:`VariantAggregateRow`：
  ``GET /variants`` 的服务端排序参数 + 单行响应。

DESIGN GAP 备注（W22-T4）：``StoryVariant`` 上目前没有 ``estimated_cost``
等成本字段，因此 ROI 无法在后端真实计算。当前契约把 :attr:`KpiSummary.roi`
显式标注为 ``Optional[float]``：
- 当未来引入成本字段后，service 层会回填 ``(gmv - cost) / cost``；
- 在此之前一律返回 ``None``，由前端展示 "N/A" 占位。
切勿在本期改动 schema 引入 ``estimated_cost`` —— 该改造属另一刀。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class AnalyticsDimension(str, Enum):
    """归因维度枚举。"""

    formula = "formula"
    hook = "hook"
    archetype = "archetype"
    platform = "platform"


class AnalyticsMetric(str, Enum):
    """指标枚举（与 :class:`StoryOutcome` 字段对应）。

    * SUM 类：``gmv`` / ``cart_clicks`` / ``orders`` / ``interactions``。
    * AVG 类：``completion_rate_full``。
    """

    gmv = "gmv"
    cart_clicks = "cart_clicks"
    completion_rate_full = "completion_rate_full"
    orders = "orders"
    interactions = "interactions"


class ChartDataPoint(BaseModel):
    """单个聚合数据点。"""

    model_config = ConfigDict(extra="forbid")

    dimension_id: str = Field(..., description="维度稳定主键")
    dimension_name: str = Field(..., description="维度可读名称（用于图表 label）")
    metric_value: float = Field(..., description="聚合数值；rate 为 [0, 1]，量为 ≥0")


class ChartDataResponse(BaseModel):
    """归因聚合响应壳。"""

    model_config = ConfigDict(extra="forbid")

    dimension: AnalyticsDimension
    metric: AnalyticsMetric
    points: list[ChartDataPoint] = Field(default_factory=list)


class KpiRange(str, Enum):
    """KPI 摘要查询窗口枚举（向后取若干自然日的 outcome）。

    选用 7d / 30d / 90d 三档：
    - 7d：单周快速复盘；
    - 30d：默认（与运营月度复盘对齐）；
    - 90d：单季度趋势观察。
    """

    last_7d = "7d"
    last_30d = "30d"
    last_90d = "90d"


class KpiSummary(BaseModel):
    """``GET /commerce/analytics/kpis`` 响应。

    全部字段使用 ``Optional[float]`` —— 在窗口内无任何 outcome 时返回
    ``None``，由前端显示 "N/A"，避免把"0"误读为"真正发生过、但全部失败"。

    ROI 当前永远为 ``None``，原因见模块 docstring 的 DESIGN GAP 段。
    """

    model_config = ConfigDict(extra="forbid")

    range: KpiRange = Field(..., description="本次查询的时间窗口")
    gmv_total: float | None = Field(
        None, description="窗口内 GMV 总和（人民币元）；窗口为空时为 None",
    )
    roi: float | None = Field(
        None,
        description=(
            "ROI = (gmv - estimated_cost) / estimated_cost。"
            "成本字段尚未在 StoryVariant 落地（DESIGN GAP），当前永远返回 None。"
        ),
    )
    completion_rate_avg: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="窗口内 completion_rate_full 平均值（0~1）；无数据时 None",
    )
    cart_rate_avg: float | None = Field(
        None,
        ge=0.0,
        description=(
            "窗口内『加购率』平均值（cart_clicks / plays），分母为 0 的样本"
            "被剔除，避免拉爆均值。"
        ),
    )
    sample_size: int = Field(
        0,
        ge=0,
        description="窗口内参与聚合的 outcome 行数（用于前端展示置信度）",
    )


class VariantSortBy(str, Enum):
    """变体对比表的可排序字段。

    与 :class:`VariantAggregateRow` 的可数值字段一一对应；前端 antd Table
    的 sorter 会把 columnKey 映射为该枚举，避免前端任意 SQL 注入。
    """

    gmv = "gmv"
    plays = "plays"
    cart_clicks = "cart_clicks"
    orders = "orders"
    completion_rate_full = "completion_rate_full"
    cart_rate = "cart_rate"
    recorded_at = "recorded_at"


class VariantSortDir(str, Enum):
    """排序方向；与 antd Table 的 ``ascend`` / ``descend`` 显式映射。"""

    asc = "asc"
    desc = "desc"


class VariantAggregateRow(BaseModel):
    """变体级聚合的单行（按 variant_id 折叠所有 outcome）。

    业务语义：
    - 数值列均使用 ``SUM(outcome.X)``；
    - 完播率走 AVG（与 KPI 摘要一致，rate 类指标避免 SUM 累加）；
    - ``cart_rate`` 由后端在 SQL 端算 ``SUM(cart_clicks) / NULLIF(SUM(plays), 0)``，
      前端不二次除法，避免视图各自实现导致不一致。
    """

    model_config = ConfigDict(extra="forbid")

    variant_id: str = Field(..., description="变体 ID（StoryVariant.id）")
    variant_name: str = Field(
        "",
        description=(
            "变体可读名（暂取 ``script_full_text`` 首 32 字符，"
            "未来落地正式 ``name`` 字段后切换）。"
        ),
    )
    formula_id: str | None = Field(None, description="所属公式 ID")
    formula_name: str | None = Field(None, description="所属公式名（join StoryFormula）")
    archetype: str | None = Field(None, description="品牌人格 ID")
    is_champion: bool = Field(False, description="是否冠军变体（A/B 决出后置位）")
    plays: int = Field(0, ge=0, description="窗口内累计播放量")
    completion_rate_full: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="窗口内完播率均值；无数据时 None",
    )
    cart_clicks: int = Field(0, ge=0, description="窗口内累计加购点击")
    cart_rate: float | None = Field(
        None,
        ge=0.0,
        description=(
            "窗口内加购率（SUM(cart_clicks) / SUM(plays)）；"
            "总播放为 0 时返回 None"
        ),
    )
    orders: int = Field(0, ge=0, description="窗口内累计订单数")
    gmv: float = Field(0.0, ge=0.0, description="窗口内累计 GMV")
    outcome_count: int = Field(0, ge=0, description="该变体在窗口内的 outcome 行数")


class VariantAggregateListResponse(BaseModel):
    """``GET /commerce/analytics/variants`` 分页响应壳。"""

    model_config = ConfigDict(extra="forbid")

    items: list[VariantAggregateRow] = Field(default_factory=list)
    total: int = Field(0, ge=0, description="窗口内变体总数（用于前端分页）")
    offset: int = Field(0, ge=0)
    limit: int = Field(20, ge=1)


__all__ = [
    "AnalyticsDimension",
    "AnalyticsMetric",
    "ChartDataPoint",
    "ChartDataResponse",
    "KpiRange",
    "KpiSummary",
    "VariantSortBy",
    "VariantSortDir",
    "VariantAggregateRow",
    "VariantAggregateListResponse",
]
