"""信息提取端点：实体合并、变体分析、项目级提取。"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.chains.agents import (
    ElementExtractorAgent,
    EntityMergerAgent,
    VariantAnalyzerAgent,
)
from app.chains.agents.script_processing_agents import (
    EntityMergeResult,
    VariantAnalysisResult,
    StudioScriptExtractionDraft,
)
from app.dependencies import get_db, get_llm, get_nothinking_llm
from app.schemas.common import ApiResponse, success_response
from app.services.script_processing_tasks import (
    create_extract_task,
    create_merge_task,
    create_variant_task,
    pick_merge_relation_entity_id,
    pick_variant_relation_entity_id,
    spawn_extract_task,
    spawn_merge_task,
    spawn_variant_task,
)
from app.services.script_extraction_cache import (
    build_script_extract_cache_key,
    get_cached_script_extract,
    set_cached_script_extract,
)
from app.services.studio import (
    sync_shot_extracted_candidates_from_draft,
    sync_shot_extracted_dialogue_candidates_from_draft,
)
from app.services.studio.shot_semantic_defaults import (
    apply_shot_semantic_defaults_from_draft,
)
from app.api.v1.routes.film.common import AsyncTaskCreateRead

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# EntityMergerAgent - 实体合并
# ============================================================================


class EntityMergerRequest(BaseModel):
    """实体合并请求。"""

    project_id: str | None = Field(None, description="项目 ID（异步任务关联可选）")
    chapter_id: str | None = Field(None, description="章节 ID（异步任务关联可选）")
    all_shot_extractions: list[dict[str, Any]] = Field(
        ..., description="所有镜头提取结果（ShotElementExtractionResult 的序列化形式）"
    )
    historical_library: dict[str, Any] | None = Field(
        None, description="历史实体库（可选，用于增量合并）"
    )
    script_division: dict[str, Any] | None = Field(
        None,
        description="脚本分镜结果（可选；ScriptDivisionResult 序列化），用于定位与统计",
    )
    previous_merge: dict[str, Any] | None = Field(
        None,
        description="上一次合并结果（可选；EntityMergeResult 序列化），用于冲突重试合并",
    )
    conflict_resolutions: list[dict[str, Any]] | None = Field(
        None,
        description="冲突解决建议列表（可选；用于冲突重试合并）",
    )


@router.post(
    "/merge-entities-async",
    response_model=ApiResponse[AsyncTaskCreateRead],
    summary="异步合并多镜头的实体信息",
    description="创建实体合并任务并立即返回 task_id；当前保留为预备能力，尚无真实前端入口。",
)
async def merge_entities_async(
    request: EntityMergerRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[AsyncTaskCreateRead]:
    relation_entity_id = pick_merge_relation_entity_id(
        chapter_id=request.chapter_id,
        project_id=request.project_id,
    )
    task_info = await create_merge_task(
        db,
        relation_entity_id=relation_entity_id,
        all_shot_extractions=request.all_shot_extractions,
        historical_library=request.historical_library,
        script_division=request.script_division,
        previous_merge=request.previous_merge,
        conflict_resolutions=request.conflict_resolutions,
    )
    await db.commit()
    if not task_info.reused:
        spawn_merge_task(task_info.task_id)
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
    "/merge-entities",
    response_model=ApiResponse[EntityMergeResult],
    summary="合并多镜头的实体信息",
    description=(
        "输入全部分镜提取结果（可选带上脚本分镜与历史实体库），输出合并后的实体库："
        "角色库/地点库/场景库/道具库（静态画像 + 变体列表）。"
        "该步骤会统一分配稳定ID（如 char_001/loc_001/prop_001/scene_001）。"
        "当提供 previous_merge 与 conflict_resolutions 时，将进行冲突重试合并，优先消解 conflicts 并尽量保持 ID 稳定。"
        "当前接口保留为预备能力，尚无真实前端入口。"
    ),
)
async def merge_entities(
    request: EntityMergerRequest,
    llm: BaseChatModel = Depends(get_llm),
) -> ApiResponse[EntityMergeResult]:
    """
    将多个镜头的提取结果合并，统一实体定义。

    请求体：
    - all_shot_extractions: 所有镜头的提取结果
    - historical_library: 历史实体库（可选，用于增量更新）
    - script_division: 脚本分镜结果（可选，用于定位与统计）
    - previous_merge: 上一次合并结果（可选；用于冲突重试合并）
    - conflict_resolutions: 冲突解决建议列表（可选；用于冲突重试合并）

    返回：EntityMergeResult
    - merged_library: 合并后的实体库（characters/locations/scenes/props，含 variants）
    - merge_stats: 合并统计信息
    - conflicts: 发现的冲突/待处理项
    - notes: 合并说明（可选）
    """
    try:
        agent = EntityMergerAgent(llm)
        result = agent.extract(
            all_extractions_json=json.dumps(
                request.all_shot_extractions, ensure_ascii=False
            ),
            historical_library_json=json.dumps(
                request.historical_library or {}, ensure_ascii=False
            ),
            script_division_json=json.dumps(
                request.script_division or {}, ensure_ascii=False
            ),
            previous_merge_json=json.dumps(
                request.previous_merge or {}, ensure_ascii=False
            ),
            conflict_resolutions_json=json.dumps(
                request.conflict_resolutions or [], ensure_ascii=False
            ),
        )
        return success_response(data=result)
    except Exception as e:
        logger.error(f"Entity merging failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to merge entities: {str(e)}",
        )


# ============================================================================
# VariantAnalyzerAgent - 变体分析
# ============================================================================


class VariantAnalysisRequest(BaseModel):
    """变体分析请求。"""

    project_id: str | None = Field(None, description="项目 ID（异步任务关联可选）")
    chapter_id: str | None = Field(None, description="章节 ID（异步任务关联可选）")
    merged_library: dict[str, Any] = Field(
        ...,
        description="合并后的实体库（EntityLibrary 的序列化形式；来自 EntityMerger 输出的 merged_library）",
    )
    all_shot_extractions: list[dict[str, Any]] = Field(
        ..., description="所有镜头提取结果"
    )
    script_division: dict[str, Any] | None = Field(
        None,
        description="脚本分镜结果（可选；ScriptDivisionResult 序列化），用于章节/段落分组",
    )


@router.post(
    "/analyze-variants-async",
    response_model=ApiResponse[AsyncTaskCreateRead],
    summary="异步分析服装/外形变体",
    description="创建变体分析任务并立即返回 task_id；当前保留为预备能力，尚无真实前端入口。",
)
async def analyze_variants_async(
    request: VariantAnalysisRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[AsyncTaskCreateRead]:
    relation_entity_id = pick_variant_relation_entity_id(
        chapter_id=request.chapter_id,
        project_id=request.project_id,
    )
    task_info = await create_variant_task(
        db,
        relation_entity_id=relation_entity_id,
        merged_library=request.merged_library,
        all_shot_extractions=request.all_shot_extractions,
        script_division=request.script_division,
    )
    await db.commit()
    if not task_info.reused:
        spawn_variant_task(task_info.task_id)
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
    "/analyze-variants",
    response_model=ApiResponse[VariantAnalysisResult],
    summary="分析服装/外形变体",
    description="检测角色服装/外形变化，构建演变时间线，生成章节变体建议列表与变体建议。当前接口保留为预备能力，尚无真实前端入口。",
)
async def analyze_variants(
    request: VariantAnalysisRequest,
    llm: BaseChatModel = Depends(get_llm),
) -> ApiResponse[VariantAnalysisResult]:
    """
    分析实体的变体（特别是角色服装变化）。

    请求体：
    - merged_library: 合并后的实体库
    - all_shot_extractions: 所有镜头提取结果
    - script_division: 脚本分镜结果（可选，用于章节/段落分组）

    返回：VariantAnalysisResult
    - costume_timelines: 各角色的服装演变时间线
    - variant_suggestions: 变体建议列表
    - chapter_variants: 按章节整理的变体信息
    - notes: 分析说明（可选）
    """
    try:
        agent = VariantAnalyzerAgent(llm)
        result = agent.extract(
            merged_library_json=json.dumps(request.merged_library, ensure_ascii=False),
            all_extractions_json=json.dumps(
                request.all_shot_extractions, ensure_ascii=False
            ),
            script_division_json=json.dumps(
                request.script_division or {}, ensure_ascii=False
            ),
        )
        return success_response(data=result)
    except Exception as e:
        logger.error(f"Variant analysis failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to analyze variants: {str(e)}",
        )


# ============================================================================
# ElementExtractorAgent - 项目级提取（最终输出）
# ============================================================================


class ScriptExtractRequest(BaseModel):
    """项目级信息提取请求（最终输出）。"""

    project_id: str = Field(..., description="项目 ID", min_length=1)
    chapter_id: str = Field(..., description="章节 ID", min_length=1)
    script_division: dict[str, Any] = Field(
        ..., description="分镜结果（ScriptDivisionResult 序列化）"
    )
    consistency: dict[str, Any] | None = Field(
        None, description="一致性检查结果（可选；ScriptConsistencyCheckResult 序列化）"
    )
    refresh_cache: bool = Field(False, description="是否跳过后端缓存并强制重新提取")


@router.post(
    "/extract-async",
    response_model=ApiResponse[AsyncTaskCreateRead],
    summary="异步项目级信息提取（最终输出）",
    description="创建项目级信息提取任务并立即返回 task_id；前端可通过任务状态接口轮询。",
)
async def extract_script_async(
    request: ScriptExtractRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[AsyncTaskCreateRead]:
    task_info = await create_extract_task(
        db,
        project_id=request.project_id,
        chapter_id=request.chapter_id,
        script_division=request.script_division,
        consistency=request.consistency,
        refresh_cache=request.refresh_cache,
    )
    await db.commit()
    if not task_info.reused:
        spawn_extract_task(task_info.task_id)
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
    "/extract",
    response_model=ApiResponse[StudioScriptExtractionDraft],
    summary="项目级信息提取（最终输出）",
    description="输入分镜结果（可选带一致性检查结果），输出可导入 Studio 的草稿结构（name-based，ID 由导入接口生成）。当前同步接口主要用于兼容旧调用与调试场景；页面主流程优先使用 extract-async。",
)
async def extract_script(
    request: ScriptExtractRequest,
    llm: BaseChatModel = Depends(get_nothinking_llm),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[StudioScriptExtractionDraft]:
    try:
        cache_key = build_script_extract_cache_key(
            project_id=request.project_id,
            chapter_id=request.chapter_id,
            script_division=request.script_division,
            consistency=request.consistency,
        )
        if not request.refresh_cache:
            cached = get_cached_script_extract(cache_key)
            if cached is not None:
                await sync_shot_extracted_candidates_from_draft(
                    db,
                    chapter_id=request.chapter_id,
                    draft=cached,
                )
                await sync_shot_extracted_dialogue_candidates_from_draft(
                    db,
                    chapter_id=request.chapter_id,
                    draft=cached,
                )
                await apply_shot_semantic_defaults_from_draft(
                    db,
                    chapter_id=request.chapter_id,
                    draft=cached,
                )
                await db.commit()
                return success_response(data=cached, meta={"from_cache": True})

        agent = ElementExtractorAgent(llm)
        result = agent.extract(
            project_id=request.project_id,
            chapter_id=request.chapter_id,
            script_division_json=json.dumps(
                request.script_division, ensure_ascii=False
            ),
            consistency_json=json.dumps(request.consistency or {}, ensure_ascii=False),
        )
        set_cached_script_extract(cache_key, result)
        await sync_shot_extracted_candidates_from_draft(
            db,
            chapter_id=request.chapter_id,
            draft=result,
        )
        await sync_shot_extracted_dialogue_candidates_from_draft(
            db,
            chapter_id=request.chapter_id,
            draft=result,
        )
        await apply_shot_semantic_defaults_from_draft(
            db,
            chapter_id=request.chapter_id,
            draft=result,
        )
        await db.commit()
        return success_response(data=result, meta={"from_cache": False})
    except Exception as e:
        logger.error(f"Script extraction failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to extract script: {str(e)}",
        )
