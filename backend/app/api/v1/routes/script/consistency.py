"""一致性检查端点：检测角色混淆等一致性问题。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.chains.agents import ConsistencyCheckerAgent
from app.chains.agents.script_processing_agents import ScriptConsistencyCheckResult
from app.dependencies import get_db, get_llm
from app.schemas.common import ApiResponse, success_response
from app.services.script_processing_tasks import (
    create_consistency_task,
    pick_consistency_relation_entity_id,
    spawn_consistency_task,
)
from app.api.v1.routes.film.common import AsyncTaskCreateRead

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# ConsistencyCheckerAgent - 一致性检查（基于原文）
# ============================================================================


class ScriptConsistencyCheckRequest(BaseModel):
    """一致性检查请求（角色混淆）。"""

    project_id: str | None = Field(None, description="项目 ID（异步任务关联可选）")
    chapter_id: str | None = Field(None, description="章节 ID（异步任务关联可选）")
    script_text: str = Field(..., description="完整剧本文本", min_length=1)


@router.post(
    "/check-consistency-async",
    response_model=ApiResponse[AsyncTaskCreateRead],
    summary="异步检查角色混淆一致性（基于原文）",
    description="创建一致性检查任务并立即返回 task_id；前端可通过任务状态接口轮询。",
)
async def check_consistency_async(
    request: ScriptConsistencyCheckRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[AsyncTaskCreateRead]:
    relation_entity_id = pick_consistency_relation_entity_id(
        chapter_id=request.chapter_id,
        project_id=request.project_id,
    )
    task_info = await create_consistency_task(
        db,
        relation_entity_id=relation_entity_id,
        script_text=request.script_text,
    )
    await db.commit()
    if not task_info.reused:
        spawn_consistency_task(task_info.task_id)
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
    "/check-consistency",
    response_model=ApiResponse[ScriptConsistencyCheckResult],
    summary="检查角色混淆一致性（基于原文）",
    description="检测同一角色在不同段落/镜头被赋予不同身份/行为主体导致混淆，并给出修改建议。当前同步接口主要用于兼容旧调用与调试场景；页面主流程优先使用 check-consistency-async。",
)
async def check_consistency(
    request: ScriptConsistencyCheckRequest,
    llm: BaseChatModel = Depends(get_llm),
) -> ApiResponse[ScriptConsistencyCheckResult]:
    """
    检查实体定义与分镜内容的一致性。

    请求体：
    - script_text: 完整剧本文本

    返回：ScriptConsistencyCheckResult
    - issues: 角色混淆问题列表（含 description/suggestion/affected_lines）
    - has_issues: 是否发现问题
    - summary: 总结（可选）
    """
    try:
        agent = ConsistencyCheckerAgent(llm)
        result = agent.extract(script_text=request.script_text)
        return success_response(data=result)
    except Exception as e:
        logger.error(f"Consistency checking failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check consistency: {str(e)}",
        )
