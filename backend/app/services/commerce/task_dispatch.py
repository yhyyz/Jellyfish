"""commerce/* 异步任务调度服务（W6-T3 / W19b 修订）。

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

W19b 修订（commit-before-dispatch 契约）
---------------------------------------

历史实现把 ``落 GenerationTask 行 + flush`` 与 ``celery.send_task`` 写在
同一个内部方法 ``_enqueue`` 里：先 flush 后 send_task；调用方可能再外层
``commit``。但 ``send_task`` 一旦发出，``fast`` 队列上的 worker 会几乎
即时拉到消息并执行 ``run_task_celery``，里头的 ``db.get(GenerationTask, task_id)``
有较高概率拿到 ``None``（外层事务尚未 commit），此时 worker 静默返回、
ACK 消息但不留任何错误，``GenerationTask`` 行永远停留在 ``pending``。

新契约把“落表/flush”与“发 broker 消息”严格分两段：

- :py:meth:`_prepare_enqueue` 只生成 task_id、写 ``GenerationTask`` 行并
  ``flush``，**不会** 发任何 broker 消息；返回一个 :class:`_EnqueueDescriptor`
  描述符。
- 调用方负责 ``await session.commit()``。
- 之后调用 :py:meth:`dispatch_after_commit` 把 broker 消息发出去，让
  worker 看到的是已落地的行。

这条规则一旦违反（例如在 commit 之前调用 :py:meth:`dispatch_after_commit`），
worker 仍可能竞态拿不到行；因此本模块的所有公共 ``enqueue_*`` 入口都不会
自动发消息，强制由调用方按 commit→dispatch 的顺序执行。

队列选择
--------

按 ``app.core.celery_app`` 的 ``task_routes`` 规则，``task.execute`` 落到
``fast`` 队列。3 个 commerce/* 任务都属于“分钟级”，不应该和视频/图片
等小时级任务挤同一条队列，因此本服务对 :py:meth:`celery_app.send_task`
显式传 ``queue="fast"``，让 PRE-WAVE 639727c 的路由配置不被绕过。
"""

from __future__ import annotations

import dataclasses
import logging
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


logger = logging.getLogger(__name__)


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

#: 章节级 AV 合成任务 ``task_kind``，与
#: ``app.services.studio.chapter_av_export_task`` 注册表同步。
#: P3 W19：跨路径合成——按 Shot.audio_strategy 分流（amix TTS / 原音 pass-through）
#: + ASS 硬烧 + loudnorm 响度归一化，产出"配音 + 字幕"最终成片。slow 队列。
TASK_KIND_CHAPTER_AV_EXPORT = "chapter_av_export"

#: 章节级 AV plan 任务 ``task_kind``，与
#: ``app.services.studio.chapter_av_plan_worker`` 注册表同步。
#: P3 W17 T17-7：Decision F 决策树编排，slow 队列。
TASK_KIND_CHAPTER_AV_PLAN = "chapter_av_plan"

#: 平台导出任务 ``task_kind``，与
#: ``app.services.commerce.commerce_export_worker`` 注册表同步。
#: P4 W23-T2：把章节成片按 PlatformExportPreset 转换为平台发布版本，slow 队列。
TASK_KIND_COMMERCE_EXPORT = "commerce_export"

#: 统一 Celery 入口 task name；所有 worker 通过 task_kind 二级路由。
_CELERY_ENTRY_TASK = "task.execute"

#: 默认投递队列：3 个 commerce/* 任务均属分钟级，与 worker SLA 对齐。
_DEFAULT_QUEUE = "fast"

#: 批量任务专用队列：从 worker 模块直接读取，避免常量在两个文件间漂移。
#: W14-T1 将 ``story_video_batch_generate`` 显式落到 ``slow`` 队列，
#: 避免与 ``fast`` 队列上的 commerce 单任务争抢消费者。
_STORY_BATCH_QUEUE = STORY_BATCH_QUEUE


@dataclasses.dataclass(frozen=True)
class _EnqueueDescriptor:
    """“已落表、待派发”的任务描述符（W19b 拆段契约的中间态）。

    存在原因：
        把“DB 行已 flush，但 broker 消息尚未投递”这个关键中间态显式
        建模出来，避免散落在调用方代码里靠局部变量名（``payload``、
        ``task_info`` 等）隐式表达。frozen=True 保证从产出到 dispatch
        过程中字段不可变，便于排障。

    Attributes:
        task_id: ``GenerationTask.id``，``uuid4().hex`` 形式。
        task_kind: 任务类型（与 worker 注册表 key 对齐）。
        queue: 目标 Celery 队列（``fast`` / ``slow``）。
        status: 入队后的初始状态字符串（约定固定 ``"pending"``）。
        enqueued_at: 描述符生成时刻（即 DB 行 flush 时刻），server-side。
    """

    task_id: str
    task_kind: str
    queue: str
    status: str
    enqueued_at: datetime


class CommerceTaskDispatchService:
    """剧情带货异步任务调度服务。

    把 ``commerce/*`` HTTP 入参打包成 :class:`GenerationTask` 记录，并通过
    Celery 统一入口 ``task.execute`` 触发 worker。本服务只关心“怎样落表 +
    怎样投递”，不关心 worker 内部如何执行——后者由
    :data:`app.services.worker.task_registry.task_executor_registry` 解析。

    W19b 调用契约（commit-before-dispatch）::

        descriptor = await dispatcher.enqueue_xxx(body=...)
        await session.commit()                          # 调用方必须显式 commit
        dispatcher.dispatch_after_commit(descriptor)    # 才允许向 broker 发消息

    调换上述顺序（先 dispatch 再 commit）会重现原 bug：worker 在
    ``run_task_celery`` 里 ``db.get`` 拿到 ``None`` 后静默 ACK，行永久
    pending。

    Args:
        db: 当前 HTTP 请求绑定的 :class:`AsyncSession`。本服务不会自己开
            事务、也不会调用 ``commit()``——commit 时机交由调用方掌控
            （HTTP 路由层 / worker 层），保证“行已落地”才进入 broker。
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # 公共入口：commerce/* 任务的封装（W19b 起仅落表，不再发 broker 消息）
    # ------------------------------------------------------------------

    async def enqueue_product_extract(self, body: dict[str, Any]) -> _EnqueueDescriptor:
        """落 ``task_kind=product_info_extract`` 的 :class:`GenerationTask` 行（不发 broker 消息）。

        Args:
            body: 由 :class:`app.schemas.commerce.tasks.ProductExtractRequest`
                ``model_dump`` 出来的 dict，结构由请求 schema 校验过；本服务
                只会把它原样塞进 ``payload['run_args']``，不再二次校验。

        Returns:
            :class:`_EnqueueDescriptor` 描述符（包含 task_id / task_kind /
            queue / status / enqueued_at）；调用方必须先 ``await session.commit()``
            再调 :py:meth:`dispatch_after_commit` 才会真正向 broker 发消息。
        """

        return await self._prepare_enqueue(
            task_kind=TASK_KIND_PRODUCT_INFO_EXTRACT,
            run_args=body,
        )

    async def enqueue_script_generate(self, body: dict[str, Any]) -> _EnqueueDescriptor:
        """落 ``task_kind=story_script_generate`` 的 :class:`GenerationTask` 行（不发 broker 消息）。

        Args:
            body: ``ScriptGenerateRequest.model_dump()`` 输出。

        Returns:
            :class:`_EnqueueDescriptor`；调用方必须 commit 后调
            :py:meth:`dispatch_after_commit`。
        """

        return await self._prepare_enqueue(
            task_kind=TASK_KIND_STORY_SCRIPT_GENERATE,
            run_args=body,
        )

    async def enqueue_compliance_check(self, body: dict[str, Any]) -> _EnqueueDescriptor:
        """落 ``task_kind=compliance_check`` 的 :class:`GenerationTask` 行（不发 broker 消息）。

        Args:
            body: ``ComplianceCheckRequest.model_dump()`` 输出。

        Returns:
            :class:`_EnqueueDescriptor`；调用方必须 commit 后调
            :py:meth:`dispatch_after_commit`。
        """

        return await self._prepare_enqueue(
            task_kind=TASK_KIND_COMPLIANCE_CHECK,
            run_args=body,
        )

    async def enqueue_tts_generate(self, body: dict[str, Any]) -> _EnqueueDescriptor:
        """落 ``task_kind=tts_generate`` 的 :class:`GenerationTask` 行（``fast`` 队列；不发 broker 消息）。

        与其它 commerce/* 任务一致，TTS 合成属分钟级，默认走 ``fast`` 队列；
        Worker 端会先查 ``tts_cache`` 命中、未命中再调 DashScope CosyVoice。

        Args:
            body: TTS 合成请求 dict（含 ``text`` / ``voice_pack_id`` /
                ``speed`` / ``audio_format`` / ``enable_word_timestamps``）。

        Returns:
            :class:`_EnqueueDescriptor`；调用方必须 commit 后调
            :py:meth:`dispatch_after_commit`。
        """

        return await self._prepare_enqueue(
            task_kind=TASK_KIND_TTS_GENERATE,
            run_args=body,
        )

    async def enqueue_asr_subtitle_generate(
        self, body: dict[str, Any]
    ) -> _EnqueueDescriptor:
        """落 ``task_kind=asr_subtitle_generate`` 的 :class:`GenerationTask` 行（``fast`` 队列；不发 broker 消息）。

        ``keep_native`` 路径专用：把已生成视频/音频送进 DashScope Paraformer-v2
        反推字级时间戳生成字幕。属分钟级任务（单镜头视频通常 ≤ 6s 音频，
        ASR 延迟 30-60s），与 TTS 对称走 ``fast`` 队列。

        Args:
            body: ASR 字幕反推请求 dict（至少包含 ``video_file_id``，可选
                ``language_hints`` / ``shot_id`` / ``style_id``——后两者用于
                ASR 成功后链式派发 ``shot_subtitle_render``）。

        Returns:
            :class:`_EnqueueDescriptor`；调用方必须 commit 后调
            :py:meth:`dispatch_after_commit`。
        """

        return await self._prepare_enqueue(
            task_kind=TASK_KIND_ASR_SUBTITLE_GENERATE,
            run_args=body,
        )

    async def enqueue_shot_subtitle_render(
        self, body: dict[str, Any]
    ) -> _EnqueueDescriptor:
        """落 ``task_kind=shot_subtitle_render`` 的 :class:`GenerationTask` 行（``fast`` 队列；不发 broker 消息）。

        W18 字幕渲染：把字级时间戳（``word_timestamps``）按 SubtitleStyle 渲染为
        ``.ass`` 文件，落 minio + 写 SubtitleTrack 行。属秒级任务（纯计算 +
        一次 minio 上传），走 ``fast`` 队列与 TTS / ASR 对齐。

        Args:
            body: 字幕渲染请求 dict（至少包含 ``shot_id`` / ``style_id`` /
                ``word_timestamps``，可选 ``language_code`` / ``source``）。

        Returns:
            :class:`_EnqueueDescriptor`；调用方必须 commit 后调
            :py:meth:`dispatch_after_commit`。
        """

        return await self._prepare_enqueue(
            task_kind=TASK_KIND_SHOT_SUBTITLE_RENDER,
            run_args=body,
        )

    async def enqueue_chapter_av_export(
        self, body: dict[str, Any]
    ) -> _EnqueueDescriptor:
        """落 ``task_kind=chapter_av_export`` 的 :class:`GenerationTask` 行（``slow`` 队列；不发 broker 消息）。

        W19 跨路径合成：按 ``Shot.audio_strategy`` 分流（silent_with_tts amix
        TTS / keep_native 原音 pass-through）+ 字幕硬烧 + loudnorm 响度归一化，
        产出"配音 + 字幕"成片。整章级任务通常 3-10 分钟，走 ``slow`` 队列避免
        与 fast 队列上的分钟级 worker 争抢消费者。

        Args:
            body: 章节合成请求 dict（至少包含 ``chapter_id``，可选 ``aspect`` /
                ``audio_strategy_override``）。

        Returns:
            :class:`_EnqueueDescriptor`；调用方必须 commit 后调
            :py:meth:`dispatch_after_commit`。
        """

        return await self._prepare_enqueue(
            task_kind=TASK_KIND_CHAPTER_AV_EXPORT,
            run_args=body,
            queue=_STORY_BATCH_QUEUE,
        )

    async def enqueue_chapter_av_plan(
        self, body: dict[str, Any]
    ) -> _EnqueueDescriptor:
        """落 ``task_kind=chapter_av_plan`` 的 :class:`GenerationTask` 行（``slow`` 队列；不发 broker 消息）。

        Decision F 决策树要在 TTS 合成前 reconcile (text, voice_pack,
        shot.duration) 三元组；遍历整个章节、可能反复调 LLM 改写，故走
        ``slow`` 队列以避免与 fast 队列上的分钟级任务争抢消费者。

        Args:
            body: AV plan 请求 dict，至少包含 ``chapter_id``。

        Returns:
            :class:`_EnqueueDescriptor`；调用方必须 commit 后调
            :py:meth:`dispatch_after_commit`。
        """

        return await self._prepare_enqueue(
            task_kind=TASK_KIND_CHAPTER_AV_PLAN,
            run_args=body,
            queue=_STORY_BATCH_QUEUE,
        )

    async def enqueue_commerce_export(
        self, body: dict[str, Any]
    ) -> _EnqueueDescriptor:
        """落 ``task_kind=commerce_export`` 的 :class:`GenerationTask` 行（``slow`` 队列；不发 broker 消息）。

        W23-T2 平台导出：把章节成片按 PlatformExportPreset 转换出平台衍生版本。
        单次导出包含 ffmpeg scale+pad / overlay / loudnorm 等链路，整体耗时
        与 chapter_av_export 同档（3-10 分钟），故走 ``slow`` 队列与 chapter_av_*
        系列对齐，避免与 fast 队列上的分钟级 worker 争抢消费者。

        Args:
            body: 平台导出请求 dict（必含 ``variant_id`` + ``preset_id``）。

        Returns:
            :class:`_EnqueueDescriptor`；调用方必须 commit 后调
            :py:meth:`dispatch_after_commit`。
        """

        return await self._prepare_enqueue(
            task_kind=TASK_KIND_COMMERCE_EXPORT,
            run_args=body,
            queue=_STORY_BATCH_QUEUE,
        )

    async def enqueue_story_batch(self, body: dict[str, Any]) -> _EnqueueDescriptor:
        """落 ``task_kind=story_video_batch_generate`` 批量任务行（``slow`` 队列；不发 broker 消息）。

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
            :class:`_EnqueueDescriptor`；调用方必须 commit 后调
            :py:meth:`dispatch_after_commit`。``task_id`` 即批量任务 ID，
            前端可用它后续轮询批量任务状态以拿到子任务 ID 列表。
        """

        return await self._prepare_enqueue(
            task_kind=TASK_KIND_STORY_VIDEO_BATCH_GENERATE,
            run_args=body,
            queue=_STORY_BATCH_QUEUE,
        )

    # ------------------------------------------------------------------
    # 内部辅助：所有 commerce/* 任务的统一“落表”/“派发”两段拆分
    # ------------------------------------------------------------------

    async def _prepare_enqueue(
        self,
        *,
        task_kind: str,
        run_args: dict[str, Any],
        queue: str = _DEFAULT_QUEUE,
    ) -> _EnqueueDescriptor:
        """落表 + flush，**不发 broker 消息**。调用方必须先 commit 再调
        :py:meth:`dispatch_after_commit`。

        步骤：
            1. 生成 ``uuid4().hex`` 作为任务主键；
            2. 构造 :class:`GenerationTask` 行（status=pending、progress=0、
               payload 形如 ``{"task_kind": ..., "run_args": ...}``，与
               :class:`app.core.task_manager.TaskManager.create` 出来的形态完
               全一致，方便 worker 复用 ``payload['run_args']`` 取参约定）；
            3. ``add`` + ``flush`` 进 session（**不 commit**，由调用方控制）；
            4. 返回 :class:`_EnqueueDescriptor`。

        与 W19b 之前实现的差异：
            旧实现在第 3 步 flush 之后立刻 ``celery_app.send_task``；这会让
            ``fast`` 队列上的 worker 在外层事务 commit 之前就拿到消息，
            ``db.get(GenerationTask, task_id)`` 拿到 ``None`` 后静默 ACK，
            导致行永久停留在 pending。新实现把 broker 投递抽到独立的
            :py:meth:`_dispatch_descriptor`，由调用方按 commit→dispatch
            顺序触发。

        Worker 上下文调用警告（B2 复发防护）：
            chain dispatch（例如 video_generation worker 完成后链式派发
            ASR 子任务）必须遵循同样的 prepare→commit→dispatch 三段式：
            **先 _prepare_enqueue / enqueue_xxx 拿 descriptor**，**再
            await session.commit() 让链表中的 GenerationTask 行落库**，
            **最后才能 dispatch_after_commit**。如果在 worker 内直接调
            旧风格的 ``_enqueue``（即 flush 后立刻 send_task），就会重现
            W19b-T2 修复的 race：子任务消息已投递、但父事务尚未提交，
            子 worker 拉到行时 ``db.get`` 返回 ``None`` 即静默 ACK，
            子任务永远停在 pending（B2）。
            因此本类 **不** 暴露任何“flush+send 一把梭”的入口，所有
            ``enqueue_*`` 方法都必须配合 ``dispatch_after_commit`` 使用，
            worker 也不例外。

        Args:
            task_kind: 业务任务类型；必须出现在 worker registry 中。
            run_args: 透传给 worker 的执行参数 dict。
            queue: 目标 Celery 队列；默认 ``fast``，批量任务等长耗时入口
                可显式传 ``slow``。

        Returns:
            :class:`_EnqueueDescriptor` 描述符。
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

        return _EnqueueDescriptor(
            task_id=task_id,
            task_kind=task_kind,
            queue=queue,
            status=GenerationTaskStatus.pending.value,
            enqueued_at=enqueued_at,
        )

    def _dispatch_descriptor(self, descriptor: _EnqueueDescriptor) -> None:
        """同步向 broker 投递 ``task.execute`` 消息。

        与 :py:meth:`dispatch_after_commit` 唯一的差异是命名：本方法是底层
        实现入口，``dispatch_after_commit`` 是面向调用方的语义化封装，
        强调“必须先 commit 再调”。两者目前实现一致，留两个名字便于代码
        审阅时一眼看出调用 site 是否遵循契约。

        Args:
            descriptor: :py:meth:`_prepare_enqueue` 的返回值。

        Notes:
            - 显式指定 queue：虽然 ``task_routes`` 也会把 ``task.execute*``
              路由到 ``fast``，但显式传参可以避免后续有人改路由规则时
              commerce 任务误落到其它队列；同时让单测可以直接断言 queue
              参数（``fast`` vs ``slow``）。
            - 这里是同步调用：Celery client API 本身是同步的，不能用
              ``await`` 包；调用方在 async 上下文中直接调即可。
        """

        celery_app.send_task(
            _CELERY_ENTRY_TASK,
            args=[descriptor.task_id],
            queue=descriptor.queue,
        )

    def dispatch_after_commit(self, descriptor: _EnqueueDescriptor) -> None:
        """在调用方提交事务后向 broker 发送任务消息。

        发送失败仅记录 warning，不抛异常（避免吞 commit 后的副作用）。

        为什么不抛异常：
            到这一步 :class:`GenerationTask` 行已经 commit 落地，业务上已经
            是“接受了请求”的状态。如果此时因为 broker 临时不可用等原因
            ``send_task`` 失败而抛出，调用方常见的反应是 rollback 或回滚
            view layer 的副作用——但实际上 DB 行已经 commit，无法回滚；
            外层异常处理还可能误把已 commit 的状态当成失败再做一次写入。
            因此本方法吞下异常，记录足够上下文（task_id / task_kind /
            queue），由后续“扫 pending 行重投递”机制兜底。

        Args:
            descriptor: :py:meth:`_prepare_enqueue` 的返回值；调用方必须
                确保对应 :class:`GenerationTask` 行已经 commit 到底层数据库。
        """

        try:
            self._dispatch_descriptor(descriptor)
        except Exception as exc:  # noqa: BLE001 - 兜底所有 broker 异常
            logger.warning(
                "celery send_task failed for task_id=%s task_kind=%s queue=%s: %s",
                descriptor.task_id,
                descriptor.task_kind,
                descriptor.queue,
                exc,
            )


__all__ = [
    "CommerceTaskDispatchService",
    "TASK_KIND_ASR_SUBTITLE_GENERATE",
    "TASK_KIND_CHAPTER_AV_EXPORT",
    "TASK_KIND_CHAPTER_AV_PLAN",
    "TASK_KIND_COMMERCE_EXPORT",
    "TASK_KIND_COMPLIANCE_CHECK",
    "TASK_KIND_PRODUCT_INFO_EXTRACT",
    "TASK_KIND_SHOT_SUBTITLE_RENDER",
    "TASK_KIND_STORY_SCRIPT_GENERATE",
    "TASK_KIND_STORY_VIDEO_BATCH_GENERATE",
    "TASK_KIND_TTS_GENERATE",
]
