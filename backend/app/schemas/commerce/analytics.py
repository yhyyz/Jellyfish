"""投放效果归因聚合 API 的请求/响应模型（W22-T3，P4 Wave B 2/11）。

P4 阶段在 W22-T1 已落地的 ``story_outcomes`` 之上，提供"按维度归因"的
聚合查询入口，给前端 ``/commerce/analytics`` 页面的 4 个图表（按公式 /
钩子 / 品牌人格 / 平台维度）供数。本文件只承载契约定义：

* :class:`AnalyticsDimension`：可用归因维度的枚举（与路由 path 一一对应）。
* :class:`AnalyticsMetric`：可用指标的枚举（GMV / 加购点击 / 完播率等）。
* :class:`ChartDataPoint`：单个聚合数据点 DTO。
* :class:`ChartDataResponse`：列表响应壳，附带本次查询的 dimension /
  metric 上下文，避免前端把不同维度的缓存混为一谈。
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


__all__ = [
    "AnalyticsDimension",
    "AnalyticsMetric",
    "ChartDataPoint",
    "ChartDataResponse",
]
