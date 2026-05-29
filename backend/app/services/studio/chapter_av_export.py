"""章节级 AV 合成（chapter_av_export）：活跃任务检测、可导出性校验与编排常量（P3 W19 → v0.7.2 收口）。

为什么存在：
    P3 W19 引入 ``chapter_av_export`` task_kind，与既有的 ``chapter_timeline_export``
    长期并存（后者自 v0.6.0 标 deprecated）。v0.7.2 起 ``chapter_timeline_export``
    被正式删除：W31 已落地 BGM/SFX 链路并完成兼容窗口，本模块成为章节级
    AV 合成的唯一入口。新 worker 在合成阶段会按 ``Shot.audio_strategy`` 分流
    （silent_with_tts amix TTS / keep_native 原音 pass-through）+ 字幕硬烧
    + 跨段响度归一化，产出"配音 + 字幕"的最终成片
    （``FileUsageKind.chapter_master_dubbed``）。

    本模块只承载常量与轻量查询，重业务逻辑在 ``chapter_av_export_task.py``。

做什么：
    - ``find_active_chapter_av_export_task_id``：判断同章节是否已有 pending /
      running 的 AV 合成任务，避免并发重复触发；
    - ``ensure_timeline_exportable``：导出前置校验，时间线非空且全部片段
      具备可用成片文件；v0.7.2 之前住在已删除的 ``chapter_timeline_export``
      模块，本次随老 task_kind 一起搬过来，由 ``chapter_av_export_task``
      与路由层共同消费。

设计要点：
- ``EXPORT_RELATION_TYPE = "chapter_av_export"`` 与历史 chapter_timeline_export
  显式区分，让 ``GenerationTaskLink`` 反查时不混淆。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import GenerationTask, GenerationTaskStatus
from app.models.task_links import GenerationTaskLink
from app.schemas.studio.chapter_timeline import ChapterTimelineRead, TimelineClipStatus


EXPORT_TASK_KIND = "chapter_av_export"
"""task_kind 注册键；与 worker 注册表保持一致。"""

EXPORT_RESOURCE_TYPE = "video"
"""GenerationTaskLink.resource_type；最终产物是 mp4。"""

EXPORT_RELATION_TYPE = "chapter_av_export"
"""GenerationTaskLink.relation_type。"""


async def find_active_chapter_av_export_task_id(
    db: AsyncSession,
    chapter_id: str,
) -> str | None:
    """若存在进行中的章节 AV 合成任务则返回其 task_id，否则 ``None``。

    用于路由层防重复入队（同章节同时跑两个 av_export 是浪费 + 数据库竞争）。
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


def ensure_timeline_exportable(read: ChapterTimelineRead) -> None:
    """导出前置校验：时间线非空且全部片段具备可用成片文件。

    v0.7.2 之前住在 ``chapter_timeline_export.py``（已随老 task_kind 一起删除）；
    搬到本模块后由 ``chapter_av_export_task`` 与路由层共同消费，语义不变。
    """

    if not read.segments:
        raise ValueError("时间线为空，无法导出")
    for seg in read.segments:
        if seg.clip_status != TimelineClipStatus.ready:
            raise ValueError(
                f"存在未就绪片段：shot_id={seg.shot_id} status={seg.clip_status.value}",
            )


__all__ = [
    "EXPORT_RELATION_TYPE",
    "EXPORT_RESOURCE_TYPE",
    "EXPORT_TASK_KIND",
    "ensure_timeline_exportable",
    "find_active_chapter_av_export_task_id",
]
