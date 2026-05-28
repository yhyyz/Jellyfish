"""StoryOutcome 请求/响应模型（W22-T1，P4 Wave A 1/6）。

P4 阶段激活 P1 已落地的 ``story_outcomes`` 表（参见
``backend/app/models/story_formula.py:309``），仅围绕"投放后效果手动录入"
的 CRUD 提供最小契约：

- ``StoryOutcomeCreate``：创建请求体；schema 层完成基础边界校验
  （``gmv >= 0``、``completion_rate ∈ [0, 1]``），service 层做二次兜底。
- ``StoryOutcomeUpdate``：PATCH 请求体；全部字段可选，``model_dump
  (exclude_unset=True)`` 用于实现"仅覆盖显式字段"。
- ``StoryOutcomeRead``：响应模型；字符串化 ``platform`` 枚举，便于前端
  直接渲染、避免暴露内部 Enum 实例。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.types import Platform


class StoryOutcomeCreate(BaseModel):
    """创建一条 StoryOutcome 的请求体。

    字段语义对齐 :class:`app.models.story_formula.StoryOutcome`。``id``
    与 ``created_at`` / ``updated_at`` 由数据库自动生成，不接受客户端传入。

    校验规则（schema 层硬约束）：

    * ``gmv``：必须 ≥ 0；负值由 pydantic 直接 422，service 层亦会兜底。
    * ``completion_rate_3s`` / ``completion_rate_full``：可空；非空时
      限制在 ``[0, 1]``。
    * ``plays`` / ``interactions`` / ``cart_clicks`` / ``orders``：
      非负整数；默认 0。
    """

    model_config = ConfigDict(extra="forbid")

    variant_id: str = Field(..., min_length=1, description="所属变体 ID")
    platform: Platform = Field(
        Platform.douyin,
        description="投放平台（默认抖音）",
    )
    plays: int = Field(0, ge=0, description="播放量（BigInteger，避免爆款溢出）")
    completion_rate_3s: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="3 秒完播率（0~1，未回传时为 None）",
    )
    completion_rate_full: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="完整完播率（0~1，未回传时为 None）",
    )
    interactions: int = Field(0, ge=0, description="互动量（点赞+评论+分享）")
    cart_clicks: int = Field(0, ge=0, description="加购点击")
    orders: int = Field(0, ge=0, description="订单数")
    gmv: float = Field(0.0, ge=0.0, description="GMV（人民币）")
    notes: str = Field("", description="备注")
    raw_payload: dict[str, Any] = Field(
        default_factory=dict,
        description="平台原始数据 JSON（容忍未来 schema 变化）",
    )
    recorded_at: datetime = Field(
        ...,
        description="数据记录时点（必须 ≤ now，由 service 层兜底）",
    )


class StoryOutcomeUpdate(BaseModel):
    """部分更新一条 StoryOutcome（PATCH）—— 全字段可选。

    通过 ``model_dump(exclude_unset=True)`` 只取请求中显式传入的字段，
    不会把 ``None`` 误覆盖到既有非空字段（例如 ``recorded_at``）。

    ``variant_id`` 不允许通过 PATCH 修改：变更归属应由"删除 + 重建"
    完成，避免静默改写历史记录的语义。
    """

    model_config = ConfigDict(extra="forbid")

    platform: Platform | None = None
    plays: int | None = Field(None, ge=0)
    completion_rate_3s: float | None = Field(None, ge=0.0, le=1.0)
    completion_rate_full: float | None = Field(None, ge=0.0, le=1.0)
    interactions: int | None = Field(None, ge=0)
    cart_clicks: int | None = Field(None, ge=0)
    orders: int | None = Field(None, ge=0)
    gmv: float | None = Field(None, ge=0.0)
    notes: str | None = None
    raw_payload: dict[str, Any] | None = None
    recorded_at: datetime | None = None


class StoryOutcomeRead(BaseModel):
    """StoryOutcome 只读响应。

    Enum 字段（``platform``）在序列化时降级为字符串，前端可直接渲染。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="自增主键")
    variant_id: str = Field(..., description="所属变体 ID")
    platform: str = Field(..., description="投放平台（枚举值字符串）")
    plays: int = Field(..., description="播放量")
    completion_rate_3s: float | None = Field(None, description="3 秒完播率")
    completion_rate_full: float | None = Field(None, description="完整完播率")
    interactions: int = Field(..., description="互动量")
    cart_clicks: int = Field(..., description="加购点击")
    orders: int = Field(..., description="订单数")
    gmv: float = Field(..., description="GMV")
    notes: str = Field(..., description="备注")
    raw_payload: dict[str, Any] = Field(default_factory=dict, description="平台原始数据 JSON")
    recorded_at: datetime = Field(..., description="数据记录时点")
    created_at: datetime | None = Field(None, description="创建时间")
    updated_at: datetime | None = Field(None, description="最近更新时间")


__all__ = [
    "StoryOutcomeCreate",
    "StoryOutcomeRead",
    "StoryOutcomeUpdate",
]
