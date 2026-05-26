"""章节级 AV 合成（chapter_av_export）：活跃任务检测、可导出性校验与编排常量（P3 W19）。

为什么存在：
    P3 W19 引入 ``chapter_av_export`` task_kind，与既有 ``chapter_timeline_export``
    并存（后者标 deprecated 至 v0.7.0 删除）。新 worker 在合成阶段会按
    ``Shot.audio_strategy`` 分流（silent_with_tts amix TTS / keep_native 原音
    pass-through）+ 字幕硬烧 + 跨段响度归一化，产出"配音 + 字幕"的最终成片
    （``FileUsageKind.chapter_master_dubbed``）。

    本模块只承载常量与轻量查询，重业务逻辑在 ``chapter_av_export_task.py``。

做什么：
    - ``find_active_chapter_av_export_task_id``：判断同章节是否已有 pending /
      running 的 AV 合成任务，避免并发重复触发；
    - ``ensure_av_exportable``：复用 ``ensure_timeline_exportable`` 的非空 +
      全段 ready 校验（由 worker 自行调用，本模块导出便于路由层独立调用）。

设计要点：
- ``EXPORT_RELATION_TYPE = "chapter_av_export"`` 与老的 chapter_timeline_export
  显式区分，让 ``GenerationTaskLink`` 反查时不混淆；同一章节可同时存在两个
  resource_type=video 的 link 行（一条 timeline_export，一条 av_export）。
- 与 chapter_timeline_export.py 完全同形，便于路由层模板化复用。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import GenerationTask, GenerationTaskStatus
from app.models.task_links import GenerationTaskLink


EXPORT_TASK_KIND = "chapter_av_export"
"""task_kind 注册键；与 worker 注册表保持一致。"""

EXPORT_RESOURCE_TYPE = "video"
"""GenerationTaskLink.resource_type；最终产物是 mp4，与 timeline_export 共用。"""

EXPORT_RELATION_TYPE = "chapter_av_export"
"""GenerationTaskLink.relation_type；与老 chapter_timeline_export 显式区分。"""


async def find_active_chapter_av_export_task_id(
    db: AsyncSession,
    chapter_id: str,
) -> str | None:
    """若存在进行中的章节 AV 合成任务则返回其 task_id，否则 ``None``。

    用于路由层防重复入队（同章节同时跑两个 av_export 是浪费 + 数据库竞争）。
    与 ``find_active_chapter_timeline_export_task_id`` 互不影响：两个 task_kind
    可同时存在 pending/running 状态。
    """

    stmt = (
        select(GenerationTask.id)
        .join(GenerationTaskLink, GenerationTaskLink.task_id == GenerationTask.id)
        .where(
            GenerationTask.task_kind == EXPORT_TASK_KIND,
            GenerationTaskLink.resource_type == EXPORT_RESOURCE_TYPE,
            GenerationTaskLink.relation_type == EXPORT_RELATION_TYPE,
            GenerationTaskLink.relation_entity_id == chapter_id,
            GenerationTask.status.in_(
                (
                    GenerationTaskStatus.pending,
                    GenerationTaskStatus.running,
                ),
            ),
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


__all__ = [
    "EXPORT_RELATION_TYPE",
    "EXPORT_RESOURCE_TYPE",
    "EXPORT_TASK_KIND",
    "find_active_chapter_av_export_task_id",
]
