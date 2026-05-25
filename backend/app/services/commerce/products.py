"""剧情带货商品（Product / ProductImage）service 层。

职责边界（与 ``AGENTS.md`` 第 4 条保持一致）：

- 路由层只负责收参、依赖注入、调用 service、包装 ``ApiResponse``。
- 本 service 层负责：
  * 业务逻辑（id 自动生成、name 唯一性校验、级联删除依赖于 DB）
  * 状态/数据编排（详情视图额外加载 images 子集合，列表视图刻意省略）
  * 错误语义统一（``entity_not_found`` / ``entity_already_exists``）

设计要点：
- ``Product.name`` 与 ``ProductImage(product_id, quality_level, view_angle)``
  均为 DB 唯一约束；service 层不再做 “select 后 insert” 的 race 写法，
  统一通过捕获 ``IntegrityError`` 将冲突转换为 ``HTTPException(409)``，
  避免并发场景下的脏写。
- 列表查询保持瘦：``select(Product)`` + 关键字 / 枚举字段过滤 + 分页，
  依赖通用工具 ``app.api.utils`` 提供 keyword filter / order / paginate。
- 删除依赖 DB 级 ``ON DELETE CASCADE``（``ProductImage.product_id`` 与
  ``ProjectProductLink.product_id``）；service 层只调用 ``db.delete(obj)``，
  不在 Python 端逐表清理。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.utils import apply_keyword_filter, apply_order, paginate
from app.models.commerce_assets import Product, ProductImage
from app.services.common import (
    entity_already_exists,
    entity_not_found,
)

# 列表接口允许的排序字段；其他字段一律回退到默认 ``created_at``，
# 避免前端通过任意列名注入排序导致全表扫描或语义不清的排序结果。
PRODUCT_ORDER_FIELDS = {"name", "created_at", "updated_at"}


def _serialize_product(obj: Product) -> dict[str, Any]:
    """将 ``Product`` ORM 对象转换为响应字典。

    Enum 字段统一字符串化（``.value``），不直接返回 Enum 实例，避免
    前端拿到 Python Enum 表示。``images`` 由调用方按需注入，默认空列表。
    """
    return {
        "id": obj.id,
        "name": obj.name,
        "brand": obj.brand,
        "category": obj.category.value if hasattr(obj.category, "value") else str(obj.category),
        "description": obj.description,
        "price_anchor": obj.price_anchor,
        "sku": obj.sku,
        "selling_points": list(obj.selling_points or []),
        "pain_points_solved": list(obj.pain_points_solved or []),
        "target_audience": dict(obj.target_audience or {}),
        "catchphrases": list(obj.catchphrases or []),
        "competitor_names": list(obj.competitor_names or []),
        "health_disclaimer_required": bool(obj.health_disclaimer_required),
        "visual_style": obj.visual_style.value if hasattr(obj.visual_style, "value") else str(obj.visual_style),
        "style": obj.style.value if hasattr(obj.style, "value") else str(obj.style),
        "prompt_template_id": obj.prompt_template_id,
        "created_at": obj.created_at,
        "updated_at": obj.updated_at,
        "images": [],
    }


def _serialize_product_image(obj: ProductImage) -> dict[str, Any]:
    """将 ``ProductImage`` ORM 对象转换为响应字典。"""
    return {
        "id": obj.id,
        "product_id": obj.product_id,
        "file_id": obj.file_id,
        "quality_level": obj.quality_level.value if hasattr(obj.quality_level, "value") else str(obj.quality_level),
        "view_angle": obj.view_angle.value if hasattr(obj.view_angle, "value") else str(obj.view_angle),
        "is_primary": bool(obj.is_primary),
        "width": obj.width,
        "height": obj.height,
        "fmt": obj.fmt,
        "created_at": obj.created_at,
    }


class ProductsService:
    """商品（Product / ProductImage）协调服务。

    单一会话生命周期内复用：每次接口调用通过 ``Depends(get_db)`` 注入
    新的 ``AsyncSession``，service 实例本身无状态，方法均为 ``async``。
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_products(
        self,
        *,
        q: str | None,
        category: str | None,
        style: str | None,
        visual_style: str | None,
        order: str | None,
        is_desc: bool,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """商品分页列表。

        过滤维度：关键字（name/description ilike）、category、style、visual_style；
        排序字段被白名单收敛在 ``PRODUCT_ORDER_FIELDS`` 内。
        """
        stmt = select(Product)
        stmt = apply_keyword_filter(
            stmt,
            q=q,
            fields=[Product.name, Product.description],
        )
        if category:
            stmt = stmt.where(Product.category == category)
        if style:
            stmt = stmt.where(Product.style == style)
        if visual_style:
            stmt = stmt.where(Product.visual_style == visual_style)
        stmt = apply_order(
            stmt,
            model=Product,
            order=order,
            is_desc=is_desc,
            allow_fields=PRODUCT_ORDER_FIELDS,
            default="created_at",
        )
        items, total = await paginate(
            self._db,
            stmt=stmt,
            page=page,
            page_size=page_size,
        )
        return [_serialize_product(item) for item in items], total

    async def get_product(self, product_id: str) -> dict[str, Any]:
        """商品详情：附带 images 子集合。

        通过单独的 ``select(ProductImage)`` 拉取，避免在 ORM 层依赖关系延迟
        加载（async session 下 lazy-load 会抛 ``MissingGreenlet`` 风险）。
        """
        obj = await self._db.get(Product, product_id)
        if obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=entity_not_found("Product"),
            )
        payload = _serialize_product(obj)
        images_stmt = (
            select(ProductImage)
            .where(ProductImage.product_id == product_id)
            .order_by(ProductImage.id)
        )
        images_res = await self._db.execute(images_stmt)
        payload["images"] = [
            _serialize_product_image(img) for img in images_res.scalars().all()
        ]
        return payload

    async def create_product(self, body: dict[str, Any]) -> dict[str, Any]:
        """创建商品。

        - id 缺失时自动生成 ``uuid4().hex``。
        - name 唯一性由 DB 约束保证，``IntegrityError`` 转 409。
        - schema 默认值已在 Pydantic 层应用，本方法不重复填默认。
        """
        data = dict(body)
        if not data.get("id"):
            data["id"] = uuid4().hex
        try:
            obj = Product(**data)
            self._db.add(obj)
            await self._db.flush()
            await self._db.refresh(obj)
        except IntegrityError as exc:
            await self._db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=entity_already_exists("Product"),
            ) from exc
        return _serialize_product(obj)

    async def update_product(
        self,
        product_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """部分更新商品。

        仅写入请求中显式提供的字段（由路由层通过 ``exclude_unset=True`` 剔除
        未传字段）。name 冲突仍由 DB 唯一约束保证 → 409。
        """
        obj = await self._db.get(Product, product_id)
        if obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=entity_not_found("Product"),
            )
        for field, value in body.items():
            setattr(obj, field, value)
        try:
            await self._db.flush()
            await self._db.refresh(obj)
        except IntegrityError as exc:
            await self._db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=entity_already_exists("Product"),
            ) from exc
        return _serialize_product(obj)

    async def delete_product(self, product_id: str) -> None:
        """删除商品。

        DB 级 ``ON DELETE CASCADE`` 会同步清理 ``product_images`` 与
        ``project_product_links`` 中的关联行；service 层不重复处理。
        """
        obj = await self._db.get(Product, product_id)
        if obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=entity_not_found("Product"),
            )
        await self._db.delete(obj)
        await self._db.flush()

    async def add_image(
        self,
        product_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """为商品挂一张多角度图。

        (product_id, quality_level, view_angle) 唯一约束冲突时返回 409；
        product 不存在返回 404。
        """
        product = await self._db.get(Product, product_id)
        if product is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=entity_not_found("Product"),
            )
        data = dict(body)
        data["product_id"] = product_id
        try:
            image = ProductImage(**data)
            self._db.add(image)
            await self._db.flush()
            await self._db.refresh(image)
        except IntegrityError as exc:
            await self._db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=entity_already_exists("ProductImage"),
            ) from exc
        return _serialize_product_image(image)

    async def delete_image(self, product_id: str, image_id: int) -> None:
        """删除商品图。

        必须同时校验 image 存在且归属于给定 product_id，避免越权删除其他
        商品下同名 image_id（自增主键全表唯一，但语义上需归属校验）。
        """
        image = await self._db.get(ProductImage, image_id)
        if image is None or image.product_id != product_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=entity_not_found("ProductImage"),
            )
        await self._db.delete(image)
        await self._db.flush()


__all__ = ["ProductsService"]
