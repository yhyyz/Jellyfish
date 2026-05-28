"""品牌话术规范库（BrandStyleGuide）service 层 —— W25-T3。

职责边界（与 ``AGENTS.md`` 第 4 条对齐）：

* 路由层只负责收参 / 鉴权 / 响应组织；
* 本 service 层负责：
  - 业务逻辑（id 生成、product 存在性校验、1:1 upsert 语义）；
  - 状态/数据编排（PATCH 与 POST upsert 共享 patch 路径，避免重复实现）；
  - 错误语义（``entity_not_found`` / ``entity_already_exists``，与既有
    ``ProductsService`` 保持一致）。

设计要点：

* 1:1 关系通过 ``brand_style_guides.product_id`` 上的 ``UNIQUE`` 约束在
  DB 层强制；service 层不再做 "select 后 insert" 的 race 写法，统一通过
  捕获 ``IntegrityError`` 把冲突转换成 409。
* POST 语义为 "upsert"：若该商品已存在规范，则视为部分更新；否则创建
  新行。这样前端 ``BrandStyleGuideForm`` 可以始终调用 POST 而无需先查
  状态，简化交互。
* 删除依赖 DB 级 ``ON DELETE CASCADE``（``brand_style_guides.product_id``
  → ``products.id``）；service 层只在显式 DELETE 端点上 ``db.delete(obj)``，
  product 删除时不需要在 Python 端处理。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brand_style_guide import BrandStyleGuide
from app.models.commerce_assets import Product
from app.services.common import (
    entity_already_exists,
    entity_not_found,
)


def _serialize(obj: BrandStyleGuide) -> dict[str, Any]:
    """将 ``BrandStyleGuide`` ORM 对象转成响应字典。

    JSON list 字段统一通过 ``list(...)`` 复制，避免直接共享 ORM 内部容器
    造成跨请求污染；``brand_persona_tagline`` 默认补 ""。
    """
    return {
        "id": obj.id,
        "product_id": obj.product_id,
        "forced_phrases": list(obj.forced_phrases or []),
        "banned_patterns": list(obj.banned_patterns or []),
        "required_endings": list(obj.required_endings or []),
        "brand_persona_tagline": obj.brand_persona_tagline or "",
        "created_at": obj.created_at,
        "updated_at": obj.updated_at,
    }


def _normalize_payload(body: dict[str, Any]) -> dict[str, Any]:
    """把请求 dict 中的 None 值替换成对应默认值。

    ``BrandStyleGuideUpsert`` 让前端可以省略字段（用 None 表达"不传"）；
    创建场景下需要把 None 翻译成空数组 / 空串，避免 NOT NULL 约束失败。
    """
    cleaned: dict[str, Any] = {}
    for field, default in (
        ("forced_phrases", []),
        ("banned_patterns", []),
        ("required_endings", []),
        ("brand_persona_tagline", ""),
    ):
        if field in body:
            value = body[field]
            cleaned[field] = default if value is None else value
    return cleaned


class BrandStyleGuideService:
    """品牌话术规范服务（与 Product 1:1）。

    单一会话生命周期内复用：每次接口调用通过 ``Depends(get_db)`` 注入新的
    ``AsyncSession``，service 实例本身无状态，方法均为 ``async``。
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def _require_product(self, product_id: str) -> Product:
        """确保给定 ``product_id`` 对应的商品存在；不存在 → 404。"""
        product = await self._db.get(Product, product_id)
        if product is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=entity_not_found("Product"),
            )
        return product

    async def _fetch_by_product(self, product_id: str) -> BrandStyleGuide | None:
        """按 ``product_id`` 取一条规范；不存在返回 ``None``。"""
        stmt = select(BrandStyleGuide).where(
            BrandStyleGuide.product_id == product_id
        )
        res = await self._db.execute(stmt)
        return res.scalar_one_or_none()

    async def get(self, product_id: str) -> dict[str, Any]:
        """读取商品的品牌话术规范。

        商品不存在 → 404 ``Product``；商品存在但规范不存在 → 404
        ``BrandStyleGuide``。
        """
        await self._require_product(product_id)
        obj = await self._fetch_by_product(product_id)
        if obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=entity_not_found("BrandStyleGuide"),
            )
        return _serialize(obj)

    async def upsert(
        self,
        product_id: str,
        body: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        """创建或更新品牌话术规范（POST 语义）。

        返回 ``(payload, created)``：``created`` 为 ``True`` 表示本次新建，
        路由层据此返回 201 / 200。商品不存在 → 404。
        """
        await self._require_product(product_id)
        existing = await self._fetch_by_product(product_id)
        normalized = _normalize_payload(body)

        if existing is not None:
            # 已存在 → 当作部分更新；只覆盖请求中显式提供的字段。
            for field, value in normalized.items():
                setattr(existing, field, value)
            try:
                await self._db.flush()
                await self._db.refresh(existing)
            except IntegrityError as exc:
                await self._db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=entity_already_exists("BrandStyleGuide"),
                ) from exc
            return _serialize(existing), False

        # 新建：补齐所有字段默认值，避免 NOT NULL 约束失败。
        full_payload: dict[str, Any] = {
            "id": uuid4().hex,
            "product_id": product_id,
            "forced_phrases": [],
            "banned_patterns": [],
            "required_endings": [],
            "brand_persona_tagline": "",
        }
        full_payload.update(normalized)
        try:
            obj = BrandStyleGuide(**full_payload)
            self._db.add(obj)
            await self._db.flush()
            await self._db.refresh(obj)
        except IntegrityError as exc:
            await self._db.rollback()
            # 唯一约束冲突（极小概率：并发 upsert）→ 409
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=entity_already_exists("BrandStyleGuide"),
            ) from exc
        return _serialize(obj), True

    async def patch(
        self,
        product_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """部分更新品牌话术规范（PATCH 语义）。

        与 upsert 不同，PATCH 在规范不存在时直接返回 404，不自动创建；
        body 已由路由层用 ``model_dump(exclude_unset=True)`` 收口，仅包含
        显式提供字段。
        """
        await self._require_product(product_id)
        obj = await self._fetch_by_product(product_id)
        if obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=entity_not_found("BrandStyleGuide"),
            )
        normalized = _normalize_payload(body)
        for field, value in normalized.items():
            setattr(obj, field, value)
        try:
            await self._db.flush()
            await self._db.refresh(obj)
        except IntegrityError as exc:
            await self._db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=entity_already_exists("BrandStyleGuide"),
            ) from exc
        return _serialize(obj)

    async def delete(self, product_id: str) -> None:
        """删除商品的品牌话术规范。

        商品不存在 → 404 ``Product``；商品存在但规范不存在 → 404
        ``BrandStyleGuide``。删除后再创建是合法的（DB 不缓存软删）。
        """
        await self._require_product(product_id)
        obj = await self._fetch_by_product(product_id)
        if obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=entity_not_found("BrandStyleGuide"),
            )
        await self._db.delete(obj)
        await self._db.flush()


__all__ = ["BrandStyleGuideService"]
