"""剧本分镜端点：将完整剧本文本分割为多个镜头。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.chains.agents import ScriptDividerAgent
from app.chains.agents.script_processing_agents import ScriptDivisionResult
from app.dependencies import get_db, get_nothinking_llm
from app.schemas.common import ApiResponse, success_response
from app.services.common import required_field
from app.services.script_processing_tasks import (
    create_divide_task,
    spawn_divide_task,
)
from app.services.studio.script_division import write_division_result_to_chapter
from app.api.v1.routes.film.common import AsyncTaskCreateRead

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# ScriptDividerAgent - 剧本分镜
# ============================================================================


class ScriptDividerRequest(BaseModel):
    """剧本分镜请求。"""

    script_text: str = Field(..., description="完整剧本文本", min_length=1)
    write_to_db: bool = Field(
        False, description="是否将分镜写入数据库（AI Studio shots 表）"
    )
    chapter_id: str | None = Field(
        None,
        description="章节 ID（write_to_db=true 时必填）",
        min_length=1,
    )


@router.post(
    "/divide-async",
    response_model=ApiResponse[AsyncTaskCreateRead],
    summary="异步将剧本分割为多个镜头",
    description="创建章节分镜提取任务并立即返回 task_id；前端可通过任务状态接口轮询。",
)
async def divide_script_async(
    request: ScriptDividerRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[AsyncTaskCreateRead]:
    if not request.chapter_id:
        raise HTTPException(
            status_code=400, detail=required_field("chapter_id", when="divide-async")
        )

    task_info = await create_divide_task(
        db,
        chapter_id=request.chapter_id,
        script_text=request.script_text,
        write_to_db=request.write_to_db,
    )
    await db.commit()
    if not task_info.reused:
        spawn_divide_task(task_info.task_id)
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
    "/divide",
    response_model=ApiResponse[ScriptDivisionResult],
    summary="将剧本分割为多个镜头",
    description=(
        "输入完整剧本文本，输出分镜列表（index/start_line/end_line/script_excerpt/"
        "shot_name/time_of_day）。"
        "注意：此阶段不强制稳定ID，角色以\u201c称呼/名字\u201d弱信息输出，稳定ID在合并阶段统一分配。"
        "当前同步接口主要用于兼容旧调用与调试场景；页面主流程优先使用 divide-async。"
    ),
)
async def divide_script(
    request: ScriptDividerRequest,
    llm: BaseChatModel = Depends(get_nothinking_llm),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ScriptDivisionResult]:
    """
    将完整剧本文本自动分割为多个镜头。

    请求体：
    - script_text: 完整剧本文本

    返回：ScriptDivisionResult
    - shots: 分镜列表，包含每个镜头的 index、起止行号、shot_name、script_excerpt、time_of_day
    - total_shots: 总镜头数
    - notes: 拆分说明（可选）
    """
    try:
        agent = ScriptDividerAgent(llm)
        result = agent.divide_script(script_text=request.script_text)

        if request.write_to_db:
            if not request.chapter_id:
                raise HTTPException(
                    status_code=400,
                    detail=required_field("chapter_id", when="write_to_db=true"),
                )
            await write_division_result_to_chapter(
                db,
                chapter_id=request.chapter_id,
                result=result,
            )

        return success_response(data=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Script dividing failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to divide script: {str(e)}",
        )
