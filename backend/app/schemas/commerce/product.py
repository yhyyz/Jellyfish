"""剧情带货商品（Product / ProductImage）的请求/响应模型。

设计要点：
- 请求体 ``ProductCreate`` / ``ProductUpdate`` / ``ProductImageCreate`` 全部
  使用 ``ConfigDict(extra="forbid")``，禁止前端误传未知字段，避免静默丢失。
- 默认值统一使用 “bare default”（``= "" / = [] / = None`` 等），不引入
  ``Field(default=...)``，与项目风格保持一致并降低 mypy/pyright 负担。
- 响应体 ``ProductRead`` / ``ProductImageRead`` 字符串化所有 Enum 字段
  （``category`` / ``style`` / ``visual_style`` / ``quality_level`` /
  ``view_angle``），便于前端直接渲染、避免泄露内部 Enum 实例。
- ``ProductRead.images`` 仅在“详情视图”由 service 层显式注入；列表视图返回
  默认空列表，避免每条 row 触发一次 image 子查询。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.types import (
    AssetQualityLevel,
    AssetViewAngle,
    ProductCategory,
    ProjectStyle,
    ProjectVisualStyle,
)


class ProductCreate(BaseModel):
    """创建商品请求体。

    `id` 不传则由 service 层使用 ``uuid4().hex`` 自动生成；`name` 在全库范围
    唯一（参见 ``Product.uq_products_name``），冲突由 service 层捕获
    ``IntegrityError`` 并转换为 409。
    """

    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str
    brand: str = ""
    category: ProductCategory = ProductCategory.other
    description: str = ""
    price_anchor: float | None = None
    sku: str | None = None
    selling_points: list[str] = []
    pain_points_solved: list[str] = []
    target_audience: dict[str, Any] = {}
    catchphrases: list[str] = []
    competitor_names: list[str] = []
    health_disclaimer_required: bool = False
    visual_style: ProjectVisualStyle = ProjectVisualStyle.live_action
    style: ProjectStyle
    prompt_template_id: str | None = None


class ProductUpdate(BaseModel):
    """部分更新商品（PATCH）—— 全字段可选。

    通过 ``model_dump(exclude_unset=True)`` 可只取请求中显式提供的字段，
    避免把 None 误覆盖到既有非空字段上。
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    brand: str | None = None
    category: ProductCategory | None = None
    description: str | None = None
    price_anchor: float | None = None
    sku: str | None = None
    selling_points: list[str] | None = None
    pain_points_solved: list[str] | None = None
    target_audience: dict[str, Any] | None = None
    catchphrases: list[str] | None = None
    competitor_names: list[str] | None = None
    health_disclaimer_required: bool | None = None
    visual_style: ProjectVisualStyle | None = None
    style: ProjectStyle | None = None
    prompt_template_id: str | None = None


class ProductImageRead(BaseModel):
    """商品图响应模型。"""

    id: int
    product_id: str
    file_id: str | None
    quality_level: str
    view_angle: str
    is_primary: bool
    width: int | None
    height: int | None
    fmt: str | None
    created_at: datetime


class ProductRead(BaseModel):
    """商品响应模型。

    `images` 仅在“详情”接口由 service 层填充；列表接口返回空列表。
    """

    id: str
    name: str
    brand: str
    category: str
    description: str
    price_anchor: float | None
    sku: str | None
    selling_points: list[str]
    pain_points_solved: list[str]
    target_audience: dict[str, Any]
    catchphrases: list[str]
    competitor_names: list[str]
    health_disclaimer_required: bool
    visual_style: str
    style: str
    prompt_template_id: str | None
    created_at: datetime
    updated_at: datetime
    images: list[ProductImageRead] = []


class ProductImageCreate(BaseModel):
    """上传/挂载商品图请求体。

    在 (product_id, quality_level, view_angle) 维度上唯一（参见
    ``ProductImage.uq_product_images_quality_angle``），重复时 service 层
    捕获 ``IntegrityError`` 并转 409。
    """

    model_config = ConfigDict(extra="forbid")

    file_id: str
    quality_level: AssetQualityLevel = AssetQualityLevel.medium
    view_angle: AssetViewAngle = AssetViewAngle.front
    is_primary: bool = False
    width: int | None = None
    height: int | None = None
    fmt: str | None = None


__all__ = [
    "ProductCreate",
    "ProductImageCreate",
    "ProductImageRead",
    "ProductRead",
    "ProductUpdate",
]
