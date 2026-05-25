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

#: 商品信息抽取任务 ``task_kind``，与 worker 注册表保持一致。
TASK_KIND_PRODUCT_INFO_EXTRACT = "product_info_extract"

#: 剧情脚本生成任务 ``task_kind``，与 worker 注册表保持一致。
TASK_KIND_STORY_SCRIPT_GENERATE = "story_script_generate"

#: 合规检查任务 ``task_kind``，与 worker 注册表保持一致。
TASK_KIND_COMPLIANCE_CHECK = "compliance_check"

#: 统一 Celery 入口 task name；所有 worker 通过 task_kind 二级路由。
_CELERY_ENTRY_TASK = "task.execute"

#: 默认投递队列：3 个 commerce/* 任务均属分钟级，与 worker SLA 对齐。
_DEFAULT_QUEUE = "fast"


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

    # ------------------------------------------------------------------
    # 内部辅助：所有 commerce/* 任务的统一落表+投递逻辑
    # ------------------------------------------------------------------

    async def _enqueue(
        self,
        *,
        task_kind: str,
        run_args: dict[str, Any],
    ) -> dict[str, Any]:
        """统一落表 + Celery 投递的内部实现。

        步骤：
            1. 生成 ``uuid4().hex`` 作为任务主键；
            2. 构造 :class:`GenerationTask` 行（status=pending、progress=0、
               payload 形如 ``{"task_kind": ..., "run_args": ...}``，与
               :class:`app.core.task_manager.TaskManager.create` 出来的形态完
               全一致，方便 worker 复用 ``payload['run_args']`` 取参约定）；
            3. ``add`` + ``flush`` 进 session；不在此处 commit；
            4. 调用 ``celery_app.send_task("task.execute", args=[task_id], queue="fast")``
               把任务塞到 fast 队列。

        Args:
            task_kind: 业务任务类型；必须出现在 worker registry 中。
            run_args: 透传给 worker 的执行参数 dict。

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

        # 显式指定 queue="fast"：虽然 task_routes 也会把 ``task.execute*`` 路
        # 由到 fast，但显式传参可以避免后续有人改路由规则时 commerce 任务
        # 误落到 slow 队列；同时让单测可以直接断言 queue 参数。
        celery_app.send_task(
            _CELERY_ENTRY_TASK,
            args=[task_id],
            queue=_DEFAULT_QUEUE,
        )

        return {
            "task_id": task_id,
            "task_kind": task_kind,
            "status": GenerationTaskStatus.pending.value,
            "enqueued_at": enqueued_at,
        }


__all__ = [
    "CommerceTaskDispatchService",
    "TASK_KIND_COMPLIANCE_CHECK",
    "TASK_KIND_PRODUCT_INFO_EXTRACT",
    "TASK_KIND_STORY_SCRIPT_GENERATE",
]
