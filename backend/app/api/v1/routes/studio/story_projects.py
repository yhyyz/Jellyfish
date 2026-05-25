"""剧情带货项目接口（kind=commerce_story，W6-T2，P1 阶段）。

包含 6 条路径：

- ``GET    /api/v1/studio/story-projects``                     列表
- ``POST   /api/v1/studio/story-projects``                     创建（Project + CommerceStoryConfig 单事务）
- ``GET    /api/v1/studio/story-projects/{id}``                详情
- ``PATCH  /api/v1/studio/story-projects/{id}/config``         配置更新
- ``POST   /api/v1/studio/story-projects/{id}/products/{pid}`` 商品挂载
- ``DELETE /api/v1/studio/story-projects/{id}/products/{pid}`` 商品取消挂载

业务约束在 :class:`app.services.commerce.story_projects.StoryProjectsService`
中集中实现，本路由层只负责参数解析与响应组装。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.commerce.story_project import (
    ProjectProductLinkCreate,
    ProjectProductLinkRead,
    StoryProjectConfigUpdate,
    StoryProjectCreate,
    StoryProjectRead,
)
from app.schemas.common import (
    ApiResponse,
    created_response,
    empty_response,
    success_response,
)
from app.services.commerce.story_projects import StoryProjectsService

router = APIRouter()


@router.get(
    "",
    response_model=ApiResponse[list[StoryProjectRead]],
    summary="剧情带货项目列表（仅 kind=commerce_story）",
)
async def list_story_projects(
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[StoryProjectRead]]:
    """返回所有 commerce_story 项目，附带 1:1 配置。"""
    service = StoryProjectsService(db)
    items = await service.list_projects()
    return success_response([StoryProjectRead.model_validate(x) for x in items])


@router.post(
    "",
    response_model=ApiResponse[StoryProjectRead],
    status_code=status.HTTP_201_CREATED,
    summary="创建剧情带货项目（Project + CommerceStoryConfig 单事务）",
)
async def create_story_project(
    body: StoryProjectCreate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[StoryProjectRead]:
    """同事务创建 Project（kind=commerce_story 强制）+ CommerceStoryConfig。"""
    service = StoryProjectsService(db)
    payload = await service.create(body)
    return created_response(StoryProjectRead.model_validate(payload))


@router.get(
    "/{project_id}",
    response_model=ApiResponse[StoryProjectRead],
    summary="剧情带货项目详情",
)
async def get_story_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[StoryProjectRead]:
    """读取项目详情（含 1:1 CommerceStoryConfig）。"""
    service = StoryProjectsService(db)
    payload = await service.get_detail(project_id)
    return success_response(StoryProjectRead.model_validate(payload))


@router.patch(
    "/{project_id}/config",
    response_model=ApiResponse[StoryProjectRead],
    summary="更新剧情带货项目配置（仅 CommerceStoryConfig 字段）",
)
async def update_story_project_config(
    project_id: str,
    body: StoryProjectConfigUpdate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[StoryProjectRead]:
    """patch CommerceStoryConfig；不动 Project 核心字段。"""
    service = StoryProjectsService(db)
    payload = await service.update_config(project_id, body)
    return success_response(StoryProjectRead.model_validate(payload))


@router.post(
    "/{project_id}/products/{product_id}",
    response_model=ApiResponse[ProjectProductLinkRead],
    status_code=status.HTTP_201_CREATED,
    summary="为剧情带货项目挂载商品",
)
async def link_story_project_product(
    project_id: str,
    product_id: str,
    body: ProjectProductLinkCreate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ProjectProductLinkRead]:
    """在 ``project_product_links`` 上 INSERT 一条项目级挂载。"""
    service = StoryProjectsService(db)
    link = await service.link_product(project_id, product_id, body)
    return created_response(ProjectProductLinkRead.model_validate(link))


@router.delete(
    "/{project_id}/products/{product_id}",
    response_model=ApiResponse[None],
    summary="取消剧情带货项目的商品挂载",
)
async def unlink_story_project_product(
    project_id: str,
    product_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    """从 ``project_product_links`` 上删除 (project_id, product_id) 项目级挂载。"""
    service = StoryProjectsService(db)
    await service.unlink_product(project_id, product_id)
    return empty_response()
