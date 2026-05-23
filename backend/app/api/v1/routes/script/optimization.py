"""优化/精简端点：基于一致性检查优化剧本、智能精简剧本。"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.chains.agents import ScriptOptimizerAgent, ScriptSimplifierAgent
from app.chains.agents.script_processing_agents import (
    ScriptOptimizationResult,
    ScriptSimplificationResult,
)
from app.dependencies import get_db, get_llm
from app.schemas.common import ApiResponse, success_response
from app.services.script_processing_tasks import (
    create_script_optimization_task,
    create_script_simplification_task,
    pick_analysis_relation_entity_id,
    spawn_script_optimization_task,
    spawn_script_simplification_task,
)
from app.api.v1.routes.film.common import AsyncTaskCreateRead

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# ScriptOptimizerAgent - 剧本优化（非主线，按需触发）
# ============================================================================


class ScriptOptimizeRequest(BaseModel):
    """剧本优化请求（基于一致性检查结果）。"""

    project_id: str | None = Field(None, description="项目 ID（异步任务关联可选）")
    chapter_id: str | None = Field(None, description="章节 ID（异步任务关联可选）")
    script_text: str = Field(..., description="原文剧本文本", min_length=1)
    consistency: dict[str, Any] = Field(
        ..., description="一致性检查输出（ScriptConsistencyCheckResult 序列化）"
    )


class ScriptSimplifyRequest(BaseModel):
    """智能精简剧本请求。"""

    project_id: str | None = Field(None, description="项目 ID（异步任务关联可选）")
    chapter_id: str | None = Field(None, description="章节 ID（异步任务关联可选）")
    script_text: str = Field(..., description="原文剧本文本", min_length=1)


@router.post(
    "/optimize-script-async",
    response_model=ApiResponse[AsyncTaskCreateRead],
    summary="异步基于一致性检查优化剧本",
    description="创建剧本优化任务并立即返回 task_id；前端可通过任务状态接口轮询。",
)
async def optimize_script_async(
    request: ScriptOptimizeRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[AsyncTaskCreateRead]:
    relation_entity_id = pick_analysis_relation_entity_id(
        chapter_id=request.chapter_id,
        project_id=request.project_id,
        endpoint="optimize-script-async",
    )
    task_info = await create_script_optimization_task(
        db,
        relation_entity_id=relation_entity_id,
        script_text=request.script_text,
        consistency=request.consistency,
    )
    await db.commit()
    if not task_info.reused:
        spawn_script_optimization_task(task_info.task_id)
    return success_response(
        AsyncTaskCreateRead(
            task_id=task_info.task_id,
            status=task_info.status,
            reused=task_info.reused,
            relation_type=task_info.relation_type,
            relation_entity_id=task_info.relation_entity_id,
        )
    )


@router.post(
    "/optimize-script",
    response_model=ApiResponse[ScriptOptimizationResult],
    summary="基于一致性检查优化剧本",
    description="将一致性检查输出及原文作为输入，生成优化后的剧本（尽量少改，只改与角色混淆 issues 相关段落）。当前同步接口主要用于兼容旧调用与调试场景；页面主流程优先使用 optimize-script-async。",
)
async def optimize_script(
    request: ScriptOptimizeRequest,
    llm: BaseChatModel = Depends(get_llm),
) -> ApiResponse[ScriptOptimizationResult]:
    """
    输入原文 + 一致性检查输出，生成优化后的剧本。
    """
    try:
        agent = ScriptOptimizerAgent(llm)
        result = agent.extract(
            script_text=request.script_text,
            consistency_json=json.dumps(request.consistency, ensure_ascii=False),
        )
        return success_response(data=result)
    except Exception as e:
        logger.error(f"Script optimization failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to optimize script: {str(e)}",
        )


@router.post(
    "/simplify-script",
    response_model=ApiResponse[ScriptSimplificationResult],
    summary="智能精简剧本",
    description="在保留剧情主体并保证剧情连续的前提下精简剧本文本。当前同步接口主要用于兼容旧调用与调试场景；页面主流程优先使用 simplify-script-async。",
)
async def simplify_script(
    request: ScriptSimplifyRequest,
    llm: BaseChatModel = Depends(get_llm),
) -> ApiResponse[ScriptSimplificationResult]:
    """输入原文剧本，输出精简后的文本与精简策略摘要。"""
    try:
        agent = ScriptSimplifierAgent(llm)
        result = agent.extract(script_text=request.script_text)
        return success_response(data=result)
    except Exception as e:
        logger.error(f"Script simplification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to simplify script: {str(e)}",
        )


@router.post(
    "/simplify-script-async",
    response_model=ApiResponse[AsyncTaskCreateRead],
    summary="异步智能精简剧本",
    description="创建剧本精简任务并立即返回 task_id；前端可通过任务状态接口轮询。",
)
async def simplify_script_async(
    request: ScriptSimplifyRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[AsyncTaskCreateRead]:
    relation_entity_id = pick_analysis_relation_entity_id(
        chapter_id=request.chapter_id,
        project_id=request.project_id,
        endpoint="simplify-script-async",
    )
    task_info = await create_script_simplification_task(
        db,
        relation_entity_id=relation_entity_id,
        script_text=request.script_text,
    )
    await db.commit()
    if not task_info.reused:
        spawn_script_simplification_task(task_info.task_id)
    return success_response(
        AsyncTaskCreateRead(
            task_id=task_info.task_id,
            status=task_info.status,
            reused=task_info.reused,
            relation_type=task_info.relation_type,
            relation_entity_id=task_info.relation_entity_id,
        )
    )
