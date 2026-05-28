"""Studio 品牌话术规范库（BrandStyleGuide）CRUD —— W25-T3。

挂载在 ``Product`` 子资源路径 ``/studio/products/{product_id}/brand-style-guide`` 下，
体现 1:1 per-Product 的 D-BRAND-SCOPE 决策（每个商品至多一份规范）。

职责（与 ``AGENTS.md`` 第 4 条对齐）：

* 路由层只负责：参数解析、依赖注入、调用 service、包装 ``ApiResponse`` 响应壳；
* 业务逻辑（id 生成、product 存在性校验、upsert / patch / cascade 删除）下沉到
  :class:`BrandStyleGuideService`。

挂载位置：在 ``backend/app/api/v1/__init__.py`` 中以
``/studio/products/{product_id}/brand-style-guide`` 子路径注册，与现有
``/studio/products`` CRUD 共存（不复用 ``products.router`` 的前缀，避免 race-
aware 风险——本任务与 sibling 任务 T25-1 / T25-2 并行，独立挂载更稳）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.common import (
    ApiResponse,
    created_response,
    empty_response,
    success_response,
)
from app.schemas.studio.brand_style_guide import (
    BrandStyleGuideRead,
    BrandStyleGuideUpsert,
)
from app.services.commerce.brand_style_guide_service import (
    BrandStyleGuideService,
)

router = APIRouter()


@router.get(
    "/products/{product_id}/brand-style-guide",
    response_model=ApiResponse[BrandStyleGuideRead],
    summary="读取商品的品牌话术规范",
)
async def get_brand_style_guide(
    product_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[BrandStyleGuideRead]:
    """读取指定商品的品牌话术规范；商品或规范不存在 → 404。"""
    service = BrandStyleGuideService(db)
    payload = await service.get(product_id)
    return success_response(BrandStyleGuideRead.model_validate(payload))


@router.post(
    "/products/{product_id}/brand-style-guide",
    response_model=ApiResponse[BrandStyleGuideRead],
    summary="创建或更新（upsert）商品的品牌话术规范",
)
async def upsert_brand_style_guide(
    product_id: str,
    body: BrandStyleGuideUpsert,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[BrandStyleGuideRead]:
    """upsert 语义：商品已有规范 → 部分更新；尚无规范 → 创建。

    HTTP 状态码：新建返回 201，更新返回 200，便于前端区分。FastAPI 在
    decorator 上无法表达 "条件性 status_code"，因此通过注入 ``Response``
    动态设置 ``response.status_code``。
    """
    service = BrandStyleGuideService(db)
    payload, created = await service.upsert(
        product_id,
        body.model_dump(exclude_unset=True),
    )
    model = BrandStyleGuideRead.model_validate(payload)
    if created:
        response.status_code = status.HTTP_201_CREATED
        return created_response(model)
    return success_response(model)


@router.patch(
    "/products/{product_id}/brand-style-guide",
    response_model=ApiResponse[BrandStyleGuideRead],
    summary="部分更新商品的品牌话术规范",
)
async def patch_brand_style_guide(
    product_id: str,
    body: BrandStyleGuideUpsert,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[BrandStyleGuideRead]:
    """部分更新；规范不存在时返回 404（与 POST upsert 区分开）。"""
    service = BrandStyleGuideService(db)
    payload = await service.patch(
        product_id,
        body.model_dump(exclude_unset=True),
    )
    return success_response(BrandStyleGuideRead.model_validate(payload))


@router.delete(
    "/products/{product_id}/brand-style-guide",
    response_model=ApiResponse[None],
    status_code=status.HTTP_200_OK,
    summary="删除商品的品牌话术规范",
)
async def delete_brand_style_guide(
    product_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    """删除商品的品牌话术规范；不存在返回 404。

    商品被删除时由 DB 级 ``ON DELETE CASCADE`` 同步清理，本接口仅用于
    前端"清空规范"场景。
    """
    service = BrandStyleGuideService(db)
    await service.delete(product_id)
    return empty_response()


__all__: list[str] = ["router"]

