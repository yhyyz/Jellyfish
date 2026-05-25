"""StoryVariant 读写接口（W6-T2，P1 阶段）。

仅暴露 2 条路径：

- ``GET  /api/v1/studio/story-variants?project_id={id}``：按项目过滤
  列出变体，可选 ``chapter_id`` / ``status`` 进一步收敛。
- ``POST /api/v1/studio/story-variants``：手动创建变体；服务层强制
  ``status=draft`` / ``is_champion=False`` / ``compliance_score=0``。

P2 路径（``PATCH .../{id}/champion`` 等）在本期不实现，避免与 A/B
评估机制冲突。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.types import StoryVariantStatus
from app.schemas.commerce.story_variant import (
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
