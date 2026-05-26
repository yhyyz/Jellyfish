"""commerce/* 异步任务调度服务（W6-T3）。

为什么存在
----------

剧情带货链路在 P1 引入 3 个长耗时任务：商品信息抽取、剧情脚本生成、
合规检查。它们共享同一套基础设施（``GenerationTask`` 表 + Celery
``task.execute`` 入口 + worker 路由表 ``task_executor_registry``），
但 HTTP 入参形态各不相同：抽取吃 ``raw_text``、脚本生成吃 ``project_id``
等，合规检查吃 ``variant_id``。

如果把“构造 :class:`GenerationTask` 行 + 投递 Celery”的样板代码散落到
3 个 route 处理器里，路由层会重新承担业务逻辑职责（违反
``api 层只负责收参/鉴权/响应组织`` 的分层约定）。本服务把这一段统一收
到 service 层，route 只负责把请求 dict 透传过来。

队列选择
--------

按 ``app.core.celery_app`` 的 ``task_routes`` 规则，``task.execute`` 落到
``fast`` 队列。3 个 commerce/* 任务都属于“分钟级”，不应该和视频/图片
等小时级任务挤同一条队列，因此本服务对 :py:meth:`celery_app.send_task`
显式传 ``queue="fast"``，让 PRE-WAVE 639727c 的路由配置不被绕过。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery_app import celery_app
from app.models.task import GenerationDeliveryMode, GenerationTask, GenerationTaskStatus
from app.services.commerce.story_video_batch_generate_worker import (
    DEFAULT_QUEUE as STORY_BATCH_QUEUE,
    TASK_KIND as TASK_KIND_STORY_VIDEO_BATCH_GENERATE,
)

#: 商品信息抽取任务 ``task_kind``，与 worker 注册表保持一致。
TASK_KIND_PRODUCT_INFO_EXTRACT = "product_info_extract"

#: 剧情脚本生成任务 ``task_kind``，与 worker 注册表保持一致。
TASK_KIND_STORY_SCRIPT_GENERATE = "story_script_generate"

#: 合规检查任务 ``task_kind``，与 worker 注册表保持一致。
TASK_KIND_COMPLIANCE_CHECK = "compliance_check"

#: TTS 合成任务 ``task_kind``，与 ``app.services.studio.tts_generate_worker`` 注册表同步。
TASK_KIND_TTS_GENERATE = "tts_generate"

#: ASR 字幕反推任务 ``task_kind``，与
#: ``app.services.studio.asr_subtitle_generate_worker`` 注册表同步。
#: P3 W17 收尾（Decision D 修订）：``keep_native`` 路径下游 worker，
#: 用 DashScope Paraformer-v2 对模型自带原音反推字级时间戳生成字幕。
TASK_KIND_ASR_SUBTITLE_GENERATE = "asr_subtitle_generate"

#: 字幕渲染任务 ``task_kind``，与
#: ``app.services.studio.shot_subtitle_render_worker`` 注册表同步。
#: P3 W18：把字级时间戳（来自 TTS synthesize 或 ASR Paraformer-v2 反推）渲染
#: 成 ``.ass`` 字幕文件，落 minio + SubtitleTrack 表，供下游章节合成阶段烧录。
TASK_KIND_SHOT_SUBTITLE_RENDER = "shot_subtitle_render"

#: 章节级 AV plan 任务 ``task_kind``，与
#: ``app.services.studio.chapter_av_plan_worker`` 注册表同步。
#: P3 W17 T17-7：Decision F 决策树编排，slow 队列。
TASK_KIND_CHAPTER_AV_PLAN = "chapter_av_plan"

#: 统一 Celery 入口 task name；所有 worker 通过 task_kind 二级路由。
_CELERY_ENTRY_TASK = "task.execute"

#: 默认投递队列：3 个 commerce/* 任务均属分钟级，与 worker SLA 对齐。
_DEFAULT_QUEUE = "fast"

#: 批量任务专用队列：从 worker 模块直接读取，避免常量在两个文件间漂移。
#: W14-T1 将 ``story_video_batch_generate`` 显式落到 ``slow`` 队列，
#: 避免与 ``fast`` 队列上的 commerce 单任务争抢消费者。
_STORY_BATCH_QUEUE = STORY_BATCH_QUEUE


class CommerceTaskDispatchService:
    """剧情带货异步任务调度服务。

    把 ``commerce/*`` HTTP 入参打包成 :class:`GenerationTask` 记录，并通过
    Celery 统一入口 ``task.execute`` 触发 worker。本服务只关心“怎样落表 +
    怎样投递”，不关心 worker 内部如何执行——后者由
    :data:`app.services.worker.task_registry.task_executor_registry` 解析。

    Args:
        db: 当前 HTTP 请求绑定的 :class:`AsyncSession`。本服务不会自己开
            事务、也不会调用 ``commit()``——交由 :func:`app.dependencies.get_db`
            的上下文统一在响应返回前 commit，确保任务行落盘后才会被
            Celery worker 消费到。
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # 公共入口：3 个 commerce/* 任务的封装
    # ------------------------------------------------------------------

    async def enqueue_product_extract(self, body: dict[str, Any]) -> dict[str, Any]:
        """创建 ``task_kind=product_info_extract`` 的 :class:`GenerationTask` 并投递。

        Args:
            body: 由 :class:`app.schemas.commerce.tasks.ProductExtractRequest`
                ``model_dump`` 出来的 dict，结构由请求 schema 校验过；本服务
                只会把它原样塞进 ``payload['run_args']``，不再二次校验。

        Returns:
            ``{"task_id", "task_kind", "status", "enqueued_at"}`` 四元组的
            dict，可直接喂给 :class:`app.schemas.commerce.tasks.TaskEnqueueResponse`。
        """

        return await self._enqueue(
            task_kind=TASK_KIND_PRODUCT_INFO_EXTRACT,
            run_args=body,
        )

    async def enqueue_script_generate(self, body: dict[str, Any]) -> dict[str, Any]:
        """创建 ``task_kind=story_script_generate`` 的 :class:`GenerationTask` 并投递。

        Args:
            body: ``ScriptGenerateRequest.model_dump()`` 输出。
        """

        return await self._enqueue(
            task_kind=TASK_KIND_STORY_SCRIPT_GENERATE,
            run_args=body,
        )

    async def enqueue_compliance_check(self, body: dict[str, Any]) -> dict[str, Any]:
        """创建 ``task_kind=compliance_check`` 的 :class:`GenerationTask` 并投递。

        Args:
            body: ``ComplianceCheckRequest.model_dump()`` 输出。
        """

        return await self._enqueue(
            task_kind=TASK_KIND_COMPLIANCE_CHECK,
            run_args=body,
        )

    async def enqueue_tts_generate(self, body: dict[str, Any]) -> dict[str, Any]:
        """创建 ``task_kind=tts_generate`` 的 :class:`GenerationTask` 并投递（fast 队列）。

        与其它 commerce/* 任务一致，TTS 合成属分钟级，默认走 ``fast`` 队列；
        Worker 端会先查 ``tts_cache`` 命中、未命中再调 DashScope CosyVoice。

        Args:
            body: TTS 合成请求 dict（含 ``text`` / ``voice_pack_id`` /
                ``speed`` / ``audio_format`` / ``enable_word_timestamps``）。

        Returns:
            ``{"task_id", "task_kind", "status", "enqueued_at"}``。
        """

        return await self._enqueue(
            task_kind=TASK_KIND_TTS_GENERATE,
            run_args=body,
        )

    async def enqueue_asr_subtitle_generate(self, body: dict[str, Any]) -> dict[str, Any]:
        """创建 ``task_kind=asr_subtitle_generate`` 的 :class:`GenerationTask` 并投递（fast 队列）。

        ``keep_native`` 路径专用：把已生成视频/音频送进 DashScope Paraformer-v2
        反推字级时间戳生成字幕。属分钟级任务（单镜头视频通常 ≤ 6s 音频，
        ASR 延迟 30-60s），与 TTS 对称走 ``fast`` 队列。

        Args:
            body: ASR 字幕反推请求 dict（至少包含 ``video_file_id``，可选
                ``language_hints``）。

        Returns:
            ``{"task_id", "task_kind", "status", "enqueued_at"}``。
        """

        return await self._enqueue(
            task_kind=TASK_KIND_ASR_SUBTITLE_GENERATE,
            run_args=body,
        )

    async def enqueue_shot_subtitle_render(self, body: dict[str, Any]) -> dict[str, Any]:
        """创建 ``task_kind=shot_subtitle_render`` 的 :class:`GenerationTask` 并投递（fast 队列）。

        W18 字幕渲染：把字级时间戳（``word_timestamps``）按 SubtitleStyle 渲染为
        ``.ass`` 文件，落 minio + 写 SubtitleTrack 行。属秒级任务（纯计算 +
        一次 minio 上传），走 ``fast`` 队列与 TTS / ASR 对齐。

        Args:
            body: 字幕渲染请求 dict（至少包含 ``shot_id`` / ``style_id`` /
                ``word_timestamps``，可选 ``language_code`` / ``source``）。

        Returns:
            ``{"task_id", "task_kind", "status", "enqueued_at"}``。
        """

        return await self._enqueue(
            task_kind=TASK_KIND_SHOT_SUBTITLE_RENDER,
            run_args=body,
        )

    async def enqueue_chapter_av_plan(self, body: dict[str, Any]) -> dict[str, Any]:
        """创建 ``task_kind=chapter_av_plan`` 的 :class:`GenerationTask` 并投递（slow 队列）。

        Decision F 决策树要在 TTS 合成前 reconcile (text, voice_pack,
        shot.duration) 三元组；遍历整个章节、可能反复调 LLM 改写，故走
        ``slow`` 队列以避免与 fast 队列上的分钟级任务争抢消费者。

        Args:
            body: AV plan 请求 dict，至少包含 ``chapter_id``。

        Returns:
            ``{"task_id", "task_kind", "status", "enqueued_at"}``。
        """

        return await self._enqueue(
            task_kind=TASK_KIND_CHAPTER_AV_PLAN,
            run_args=body,
            queue=_STORY_BATCH_QUEUE,
        )

    async def enqueue_story_batch(self, body: dict[str, Any]) -> dict[str, Any]:
        """创建 ``task_kind=story_video_batch_generate`` 的批量任务并投递到 slow 队列。

        与其它 commerce/* 任务的差异：
            - **队列不同**：本任务落到 ``slow`` 队列，避免与 ``fast`` 队列上
              的 commerce 单任务争抢消费者；
            - **耗时不同**：本任务自身只做编排（落 N 个子任务行 + 投递），
              但等待子任务全部入库的链路允许 7200s 余量，由 worker 侧的
              ``timeout_seconds`` 控制。

        Args:
            body: 由 :class:`app.core.contracts.story.BatchGenerationRequest`
                ``model_dump`` 出来的 dict，结构由请求 schema 校验过；本服务
                只会把它原样塞进 ``payload['run_args']``，不再二次校验。

        Returns:
            ``{"task_id", "task_kind", "status", "enqueued_at"}`` 四元组的
            dict，``task_id`` 即批量任务 ID，前端可用它后续轮询批量任务
            状态以拿到子任务 ID 列表。
        """

        return await self._enqueue(
            task_kind=TASK_KIND_STORY_VIDEO_BATCH_GENERATE,
            run_args=body,
            queue=_STORY_BATCH_QUEUE,
        )

    # ------------------------------------------------------------------
    # 内部辅助：所有 commerce/* 任务的统一落表+投递逻辑
    # ------------------------------------------------------------------

    async def _enqueue(
        self,
        *,
        task_kind: str,
        run_args: dict[str, Any],
        queue: str = _DEFAULT_QUEUE,
    ) -> dict[str, Any]:
        """统一落表 + Celery 投递的内部实现。

        步骤：
            1. 生成 ``uuid4().hex`` 作为任务主键；
            2. 构造 :class:`GenerationTask` 行（status=pending、progress=0、
               payload 形如 ``{"task_kind": ..., "run_args": ...}``，与
               :class:`app.core.task_manager.TaskManager.create` 出来的形态完
               全一致，方便 worker 复用 ``payload['run_args']`` 取参约定）；
            3. ``add`` + ``flush`` 进 session；不在此处 commit；
            4. 调用 ``celery_app.send_task("task.execute", args=[task_id], queue=queue)``
               把任务投递到指定队列（默认 ``fast``）。

        Args:
            task_kind: 业务任务类型；必须出现在 worker registry 中。
            run_args: 透传给 worker 的执行参数 dict。
            queue: 目标 Celery 队列；默认 ``fast``，批量任务等长耗时入口
                可显式传 ``slow``。

        Returns:
            ``{"task_id", "task_kind", "status", "enqueued_at"}``。
        """

        task_id = uuid.uuid4().hex
        enqueued_at = datetime.now(timezone.utc).replace(tzinfo=None)
        payload: dict[str, Any] = {
            "task_kind": task_kind,
            "run_args": dict(run_args),
        }

        row = GenerationTask(
            id=task_id,
            mode=GenerationDeliveryMode.async_polling,
            task_kind=task_kind,
            status=GenerationTaskStatus.pending,
            progress=0,
            payload=payload,
            result=None,
            error="",
        )
        self.db.add(row)
        await self.db.flush()

        # 显式指定 queue：虽然 task_routes 也会把 ``task.execute*`` 路由到
        # fast，但显式传参可以避免后续有人改路由规则时 commerce 任务误落到
        # 其它队列；同时让单测可以直接断言 queue 参数（fast vs slow）。
        celery_app.send_task(
            _CELERY_ENTRY_TASK,
            args=[task_id],
            queue=queue,
        )

        return {
            "task_id": task_id,
            "task_kind": task_kind,
            "status": GenerationTaskStatus.pending.value,
            "enqueued_at": enqueued_at,
        }


__all__ = [
    "CommerceTaskDispatchService",
    "TASK_KIND_ASR_SUBTITLE_GENERATE",
    "TASK_KIND_CHAPTER_AV_PLAN",
    "TASK_KIND_COMPLIANCE_CHECK",
    "TASK_KIND_PRODUCT_INFO_EXTRACT",
    "TASK_KIND_SHOT_SUBTITLE_RENDER",
    "TASK_KIND_STORY_SCRIPT_GENERATE",
    "TASK_KIND_STORY_VIDEO_BATCH_GENERATE",
    "TASK_KIND_TTS_GENERATE",
]
