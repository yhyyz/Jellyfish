"""品牌话术规范库（BrandStyleGuide）请求/响应模型 —— W25-T3。

设计要点：

* ``BrandStyleGuideUpsert`` 同时承载 POST upsert 与 PATCH 部分更新场景：
  - POST：所有字段都有默认值（空数组 / 空串），允许前端最小化负载创建一份
    规范；
  - PATCH：service 层走 ``model_dump(exclude_unset=True)``，只覆盖请求中
    显式提供的字段。
* ``BrandStyleGuideRead`` 与 ORM 字段一一对应，``id`` / ``product_id`` 在
  服务层填好，前端只读。
* 与 ``Product`` 的关系是 1:1 可选：路由层把 ``product_id`` 放在路径中
  （子资源风格 ``/products/{product_id}/brand-style-guide``），所以请求体
  不需要重复 ``product_id`` 字段。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BrandStyleGuideUpsert(BaseModel):
    """创建 / 替换 / 部分更新品牌话术规范的请求体。

    所有字段均可选 + 有默认值，便于前端在内容尚未补齐时也能保存一份草稿。
    PATCH 场景使用 ``model_dump(exclude_unset=True)`` 仅取显式提供字段，
    POST upsert 场景使用 ``model_dump()`` 取完整对象，未传字段回落到默认。
    """

    model_config = ConfigDict(extra="forbid")

    forced_phrases: list[str] | None = None
    banned_patterns: list[str] | None = None
    required_endings: list[str] | None = None
    brand_persona_tagline: str | None = None


class BrandStyleGuideRead(BaseModel):
    """品牌话术规范响应模型（与 ORM 字段一一对应）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    product_id: str
    forced_phrases: list[str]
    banned_patterns: list[str]
    required_endings: list[str]
    brand_persona_tagline: str
    created_at: datetime
    updated_at: datetime


__all__ = [
    "BrandStyleGuideRead",
    "BrandStyleGuideUpsert",
]
