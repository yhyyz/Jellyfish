"""Studio 商品（Product）CRUD + 多角度图（ProductImage）API。

职责（与 ``AGENTS.md`` 第 4 条对齐）：
- 路由层只负责：参数解析、依赖注入、调用 service、包装 ``ApiResponse`` 响应壳；
- 业务逻辑（id 生成、唯一性、级联删除）全部下沉到 ``ProductsService``。

挂载位置：在 ``backend/app/api/v1/routes/studio/__init__.py`` 中以
``/studio/products`` 前缀注册，最终公网路径是 ``/api/v1/studio/products/...``。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.commerce import (
    ProductCreate,
    ProductImageCreate,
    ProductImageGenerationRequest,
    ProductImageGenerationResponse,
    ProductUpdate,
)
from app.schemas.common import (
    ApiResponse,
    PaginatedData,
    created_response,
    paginated_response,
    success_response,
)
from app.services.commerce.product_image_generation import ProductImageGenerationService
from app.services.commerce.products import ProductsService

router = APIRouter()


@router.get(
    "",
    response_model=ApiResponse[PaginatedData[dict[str, Any]]],
    summary="商品列表（分页）",
)
async def list_products(
    q: str | None = Query(None, description="按名称/描述模糊搜索"),
    category: str | None = Query(None, description="按 ProductCategory 过滤"),
    style: str | None = Query(None, description="按 ProjectStyle 过滤"),
    visual_style: str | None = Query(None, description="按 ProjectVisualStyle 过滤"),
    order: str | None = Query(None, description="排序字段：name/created_at/updated_at"),
    is_desc: bool = Query(False, description="是否倒序"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PaginatedData[dict[str, Any]]]:
    """商品分页列表：q 为关键字，category/style/visual_style 为枚举值过滤。"""
    service = ProductsService(db)
    items, total = await service.list_products(
        q=q,
        category=category,
        style=style,
        visual_style=visual_style,
        order=order,
        is_desc=is_desc,
        page=page,
        page_size=page_size,
    )
    return paginated_response(items, page=page, page_size=page_size, total=total)


@router.post(
    "",
    response_model=ApiResponse[dict[str, Any]],
    status_code=status.HTTP_201_CREATED,
    summary="创建商品",
)
async def create_product(
    body: ProductCreate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    """创建商品；id 缺省由 service 层生成 uuid4().hex。"""
    service = ProductsService(db)
    payload = await service.create_product(body.model_dump())
    return created_response(payload)


@router.get(
    "/{product_id}",
    response_model=ApiResponse[dict[str, Any]],
    summary="商品详情（含图片）",
)
async def get_product(
    product_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    """商品详情，附带 images 子集合（按 image.id 升序）。"""
    service = ProductsService(db)
    payload = await service.get_product(product_id)
    return success_response(payload)


@router.patch(
    "/{product_id}",
    response_model=ApiResponse[dict[str, Any]],
    summary="更新商品",
)
async def update_product(
    product_id: str,
    body: ProductUpdate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    """部分更新；仅写入请求中显式提供的字段。"""
    service = ProductsService(db)
    payload = await service.update_product(
        product_id,
        body.model_dump(exclude_unset=True),
    )
    return success_response(payload)


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除商品（级联删除关联图片和项目链接）",
)
async def delete_product(
    product_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """删除商品：DB 级 CASCADE 会清理 product_images 与 project_product_links。"""
    service = ProductsService(db)
    await service.delete_product(product_id)


@router.post(
    "/{product_id}/images",
    response_model=ApiResponse[dict[str, Any]],
    status_code=status.HTTP_201_CREATED,
    summary="添加商品图",
)
async def add_product_image(
    product_id: str,
    body: ProductImageCreate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    """挂载商品图：(product_id, quality_level, view_angle) 唯一，冲突 → 409。"""
    service = ProductsService(db)
    payload = await service.add_image(product_id, body.model_dump())
    return created_response(payload)


@router.delete(
    "/{product_id}/images/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除商品图",
)
async def delete_product_image(
    product_id: str,
    image_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    """删除指定商品下的图片；image 不属于该 product 时返回 404。"""
    service = ProductsService(db)
    await service.delete_image(product_id, image_id)


@router.post(
    "/{product_id}/images/generate",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ApiResponse[ProductImageGenerationResponse],
    summary="生成商品参考图（异步任务）",
)
async def generate_product_image(
    product_id: str,
    body: ProductImageGenerationRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ProductImageGenerationResponse]:
    """触发 image_generation 任务，结果完成后由下游 worker 自动写 ProductImage 行。

    路由职责（保持瘦身）：
        1. 自动校验入参（``ProductImageGenerationRequest`` 已声明 extra="forbid"）；
        2. 调用 :class:`ProductImageGenerationService` 完成模板解析 / 渲染 / 入队；
        3. 把 service 返回的 dict 包成 :class:`ProductImageGenerationResponse`，
           再走统一响应壳 ``ApiResponse``，状态码固定 ``202 Accepted``（语义
           与 W6-T3 ``commerce/*`` 任务入口一致：请求已接收、处理尚未完成）。
    """

    service = ProductImageGenerationService(db)
    payload = await service.enqueue_product_image_generation(
        product_id=product_id,
        view_angle=body.view_angle,
        quality_level=body.quality_level,
        reference_file_id=body.reference_file_id,
    )
    return success_response(
        ProductImageGenerationResponse.model_validate(payload),
        code=status.HTTP_202_ACCEPTED,
    )


__all__ = ["router"]
