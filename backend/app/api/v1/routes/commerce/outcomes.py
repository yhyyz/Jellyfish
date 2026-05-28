"""``/api/v1/commerce/outcomes`` 与 ``/variants/{id}/outcomes`` 路由（W22-T1）。

P4 Wave A 1/6：激活 P1 已建好的 ``story_outcomes`` 表，补齐"投放后效果
手动录入"的最小 CRUD 入口。

路径设计：

* ``GET    /commerce/variants/{variant_id}/outcomes``：按变体列出全部
  outcome（按 ``recorded_at desc`` 排序）。语义上属于"变体的子资源"，
  因此挂在 ``variants`` 路径下。
* ``POST   /commerce/outcomes``：创建一条记录；body 包含 variant_id。
* ``PATCH  /commerce/outcomes/{id}``：部分更新。
* ``DELETE /commerce/outcomes/{id}``：删除。

按 AGENTS.md 第 4 条，本文件只做"收参 + 调 service + ApiResponse 包装"，
业务校验 / 状态流转全部下沉到 ``app/services/commerce/outcome_service.py``。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.commerce.outcome import (
    StoryOutcomeCreate,
    StoryOutcomeRead,
    StoryOutcomeUpdate,
)
from app.schemas.common import ApiResponse, created_response, empty_response, success_response
from app.services.commerce.outcome_service import StoryOutcomeService

router = APIRouter()


@router.get(
    "/variants/{variant_id}/outcomes",
    response_model=ApiResponse[list[StoryOutcomeRead]],
    summary="变体投放效果列表（按 recorded_at desc 排序）",
)
async def list_outcomes_by_variant(
    variant_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[StoryOutcomeRead]]:
    """列出某个变体下的全部投放效果记录。"""
    svc = StoryOutcomeService(db)
    items = await svc.list_by_variant(variant_id)
    return success_response([StoryOutcomeRead.model_validate(item) for item in items])


@router.post(
    "/outcomes",
    response_model=ApiResponse[StoryOutcomeRead],
    status_code=status.HTTP_201_CREATED,
    summary="手动录入一条投放效果",
)
async def create_outcome(
    body: StoryOutcomeCreate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[StoryOutcomeRead]:
    """创建一条 outcome 记录。

    校验细节由 service 层兜底（``gmv >= 0`` / ``completion_rate ∈
    [0, 1]`` / ``recorded_at <= now``）。
    """
    svc = StoryOutcomeService(db)
    obj = await svc.create(body)
    return created_response(StoryOutcomeRead.model_validate(obj))


@router.patch(
    "/outcomes/{outcome_id}",
    response_model=ApiResponse[StoryOutcomeRead],
    summary="部分更新一条投放效果",
)
async def patch_outcome(
    outcome_id: int,
    body: StoryOutcomeUpdate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[StoryOutcomeRead]:
    """部分更新；仅显式传入字段会被覆盖。"""
    svc = StoryOutcomeService(db)
    obj = await svc.update(outcome_id, body)
    return success_response(StoryOutcomeRead.model_validate(obj))


@router.delete(
    "/outcomes/{outcome_id}",
    response_model=ApiResponse[None],
    summary="删除一条投放效果",
)
async def delete_outcome(
    outcome_id: int,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    """删除单条 outcome；记录不存在时返回 404。"""
    svc = StoryOutcomeService(db)
    await svc.delete(outcome_id)
    return empty_response()


__all__ = ["router"]
