"""StoryVariant 读写接口（W6-T2 + W14-T3，P1/A-B 阶段）。

P1 暴露 4 条路径：

- ``GET  /api/v1/studio/story-variants?project_id={id}``：按项目过滤
  列出变体，可选 ``chapter_id`` / ``status`` 进一步收敛。
- ``POST /api/v1/studio/story-variants``：手动创建变体；服务层强制
  ``status=draft`` / ``is_champion=False`` / ``compliance_score=0``。
- ``POST /api/v1/studio/story-variants/{id}/clone``（W14-T3）：克隆已
  有变体，可选覆盖 archetype/hook/cta/formula；新变体强制重置为
  ``draft`` / ``is_champion=False`` / ``compliance_score=0``。
- ``PATCH /api/v1/studio/story-variants/{id}/champion``（W14-T3）：在
  ``(project_id, chapter_id)`` 命名空间内单选目标为冠军，同章节其它
  变体的 ``is_champion`` 同时被清空。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.types import StoryVariantStatus
from app.schemas.commerce.story_variant import (
    StoryVariantCloneRequest,
    StoryVariantCreate,
    StoryVariantRead,
)
from app.schemas.common import ApiResponse, created_response, success_response
from app.services.commerce.story_variants import StoryVariantsService

router = APIRouter()


@router.get(
    "",
    response_model=ApiResponse[list[StoryVariantRead]],
    summary="变体列表（按 project_id 必填过滤，按 created_at desc 排序）",
)
async def list_story_variants(
    project_id: str = Query(..., description="项目 ID（必填）"),
    chapter_id: str | None = Query(None, description="章节 ID（可选过滤）"),
    variant_status: StoryVariantStatus | None = Query(
        None,
        alias="status",
        description="变体状态（可选过滤）",
    ),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[StoryVariantRead]]:
    """按 project_id 过滤变体列表。"""
    service = StoryVariantsService(db)
    items = await service.list_variants(
        project_id=project_id,
        chapter_id=chapter_id,
        status=variant_status,
    )
    return success_response([StoryVariantRead.model_validate(x) for x in items])


@router.post(
    "",
    response_model=ApiResponse[StoryVariantRead],
    status_code=status.HTTP_201_CREATED,
    summary="手动创建变体（status=draft，自动生成 id）",
)
async def create_story_variant(
    body: StoryVariantCreate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[StoryVariantRead]:
    """手动创建变体；P1 阶段不走自动化生成路径。"""
    service = StoryVariantsService(db)
    obj = await service.create(body)
    return created_response(StoryVariantRead.model_validate(obj))


@router.post(
    "/{variant_id}/clone",
    response_model=ApiResponse[dict[str, Any]],
    status_code=status.HTTP_201_CREATED,
    summary="克隆变体（W14-T3，A/B 派生；新变体强制重置为 draft）",
)
async def clone_variant(
    variant_id: str,
    body: StoryVariantCloneRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    """克隆已有变体，可选覆盖 archetype/hook/cta/formula 等 A/B 维度。"""
    service = StoryVariantsService(db)
    data = await service.clone_variant(variant_id, body)
    return created_response(data)


@router.patch(
    "/{variant_id}/champion",
    response_model=ApiResponse[dict[str, Any]],
    summary="标记冠军变体（W14-T3，同 (project, chapter) 单选）",
)
async def mark_variant_champion(
    variant_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    """将目标变体标记为冠军，并取消同章节其它变体的冠军标记。"""
    service = StoryVariantsService(db)
    data = await service.mark_champion(variant_id)
    return success_response(data)
