"""Worker —— ``story_video_batch_generate`` 任务执行器（W14-T1）。

为什么存在
----------

剧情带货链路在 W14 阶段需要支持「一次性扫描 N 个参数变体」的批量
生成场景：选定一个 (project, chapter) 后，前端期望提交一个变体网格
（公式 / 原型 / 钩子 / CTA / 调性等组合），由后端一次性入队 N 个
独立的 :data:`story_script_generate` 子任务，让 Celery 走自己的并发
策略消费这些子任务。

如果让前端循环调用 ``POST /commerce/script-generate`` N 次：

- 前端要承担「批次失败时一半成功一半失败」的清理责任；
- 没有统一的 ``parent_batch_id`` 让任务中心把这 N 行聚合成一个批次；
- 同步调用链路给浏览器和 ngnix 带来无谓的连接数压力。

把它沉淀到 worker 层，``story_video_batch_generate`` 只做一件事：
**enqueue N 个 ``story_script_generate`` 子任务行 + 在自身结果中
返回这些子任务的 task_id 列表**，让前端按子任务 ID 列表去任务中心
轮询，与既有任务系统天然兼容。

职责边界
--------

- 本 worker 不调用任何 LLM、不读 :class:`StoryVariant`、不写 variant；
- 本 worker 只负责：
  1. 用 :class:`BatchGenerationRequest` 校验入参；
  2. 为每个 ``BatchVariantSpec`` 生成 child ``task_id``；
  3. 落库 ``GenerationTask`` 子任务行（``task_kind=story_script_generate``、
     ``payload={"task_kind", "run_args", "parent_batch_id"}``）；
  4. 通过 :data:`celery_app.send_task` 把每个子任务投递到 ``fast`` 队列；
  5. 在自身 ``GenerationTask.result`` 中写入 ``child_task_ids`` 列表；
- 真正的脚本生成在子任务里完成，由 W5-T2 ``run_story_script_generate_task``
  独立处理。

队列与超时
----------

按 plan W14 D 节：

- 本 task_kind 默认 ``timeout_seconds=7200`` 秒（2 小时）：批量任务
  本身不耗时，但要给“被消费者吐回 + 子任务全部入库”的链路足够余量；
- 本 task_kind 由调度服务投递到 ``slow`` 队列：批量任务的频次较低，
  与脚本生成的「分钟级 fast 队列」保持隔离；
- 子任务依旧落到 ``fast`` 队列：与现有 ``story_script_generate`` 入口
  一致，避免被 slow 队列的低消费者数拖慢。
"""

from __future__ import annotations

import uuid
from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery_app import celery_app
from app.core.contracts.story import BatchGenerationRequest
from app.core.db import async_session_maker
from app.core.task_manager import SqlAlchemyTaskStore
from app.core.task_manager.types import TaskStatus
from app.models.task import GenerationDeliveryMode, GenerationTask, GenerationTaskStatus
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_logging import log_task_event, log_task_failure


TASK_KIND = "story_video_batch_generate"
"""注册键：与 plan ``task_kind`` 表保持一致。"""

DEFAULT_TIMEOUT_SEC: float = 7200.0
"""默认超时（秒）：plan W14 D 节给批量任务的硬约束（2 小时）。"""

DEFAULT_QUEUE: str = "slow"
"""默认 Celery 队列：批量任务调度落 slow 队列，与子任务的 fast 隔离。

被 :mod:`task_dispatch` 直接读取，避免常量在两个文件间漂移。
"""

CHILD_TASK_KIND: str = "story_script_generate"
"""子任务的 ``task_kind``，固定为 W5-T2 已注册的脚本生成任务。"""

CHILD_QUEUE: str = "fast"
"""子任务投递的 Celery 队列：与既有 ``story_script_generate`` 入口一致。"""

CELERY_ENTRY_TASK: str = "task.execute"
"""统一 Celery 入口；所有 worker 通过 ``task_kind`` 二级路由。"""

_RUNNING_PROGRESS = 5
"""进入 ``running`` 状态时的初始进度，与既有 worker 风格一致。"""

_SUCCEEDED_PROGRESS = 100
"""任务成功完成时的最终进度。"""


def _build_child_run_args(
    request: BatchGenerationRequest,
    variant_spec: Any,
) -> dict[str, Any]:
    """根据批量请求与单条变体规格，组装 ``story_script_generate`` 子任务入参。

    存在原因：
        每个子任务消费的是 :class:`ScriptGenerateRequest`-like 形态的 dict
        （``project_id`` / ``chapter_id`` / ``formula_id`` / ``product`` /
        ``audience`` / ``archetype`` / ``tone_grid`` / ``target_duration_sec``
        / ``platform`` / 可选 ``hook_pattern_id`` / ``cta_pattern_id``），
        把组装逻辑收拢到一个纯函数，便于单元测试断言「批量级共享字段
        + 变体级覆盖字段」的合并语义。

    参数:
        request: 已经过 Pydantic 校验的批量生成请求。
        variant_spec: 变体规格行（:class:`BatchVariantSpec`）。

    返回:
        子任务的 ``run_args`` dict；archetype 字段在变体未指定时回退为
        空字符串以满足 :class:`StoryGenerationVars` 的非空约束（实际
        archetype 名由调用方自行决定，worker 不在这里强制兜底）。
    """
    archetype: str = variant_spec.archetype or ""
    run_args: dict[str, Any] = {
        "project_id": request.project_id,
        "chapter_id": request.chapter_id,
        "formula_id": variant_spec.formula_id,
        "product": dict(request.product),
        "audience": dict(request.audience),
        "archetype": archetype,
        "tone_grid": dict(variant_spec.tone_grid),
        "target_duration_sec": request.target_duration_sec,
        "platform": request.platform,
    }
    if variant_spec.hook_pattern_id is not None:
        run_args["hook_pattern_id"] = variant_spec.hook_pattern_id
    if variant_spec.cta_pattern_id is not None:
        run_args["cta_pattern_id"] = variant_spec.cta_pattern_id
    if variant_spec.label is not None:
        run_args["variant_label"] = variant_spec.label
    return run_args


def _new_child_task_id() -> str:
    """生成 ``GenerationTask.id``，与 :func:`uuid.uuid4().hex` 保持一致。

    单独抽出函数便于测试通过 monkeypatch 注入确定性 ID。
    """
    return uuid.uuid4().hex


async def _persist_and_dispatch_children(
    session: AsyncSession,
    *,
    request: BatchGenerationRequest,
    parent_batch_id: str,
    send_task: Callable[..., Any],
) -> list[str]:
    """对每个变体落子任务行 + 投递 Celery，并返回所有子任务 ID。

    存在原因：
        把「拼 payload + add row + send_task」的循环体集中到一个 helper
        里，让 :func:`run_story_video_batch_generate_task` 主流程清爽，
        同时让单测能 patch ``send_task`` 后直接调用本函数验证：
        - 子任务数与 variants 数一致；
        - ``parent_batch_id`` 写入了 ``payload``；
        - 队列为 ``fast``。

    参数:
        session: 当前 worker 的 async 会话；本函数只负责 ``add`` /
            ``flush``，不在此处 ``commit``，由调用方决定事务边界。
        request: 已校验的批量生成请求。
        parent_batch_id: 当前批量任务自身的 ``GenerationTask.id``，作为
            子任务 ``payload['parent_batch_id']`` 的反查键。
        send_task: ``celery_app.send_task`` 兼容签名的可调用，便于注入
            mock；生产路径直接传 ``celery_app.send_task``。

    返回:
        与 ``request.variants`` 顺序一致的子任务 ID 列表。
    """
    child_task_ids: list[str] = []
    for variant_spec in request.variants:
        child_id = _new_child_task_id()
        child_run_args = _build_child_run_args(request, variant_spec)
        child_payload: dict[str, Any] = {
            "task_kind": CHILD_TASK_KIND,
            "run_args": child_run_args,
            "parent_batch_id": parent_batch_id,
        }
        child_row = GenerationTask(
            id=child_id,
            mode=GenerationDeliveryMode.async_polling,
            task_kind=CHILD_TASK_KIND,
            status=GenerationTaskStatus.pending,
            progress=0,
            payload=child_payload,
            result=None,
            error="",
        )
        session.add(child_row)
        await session.flush()

        send_task(
            CELERY_ENTRY_TASK,
            args=[child_id],
            queue=CHILD_QUEUE,
        )
        child_task_ids.append(child_id)
    return child_task_ids


async def run_story_video_batch_generate_task(
    task_id: str,
    run_args: dict[str, Any],
    *,
    session_factory: Callable[[], AsyncSession] | None = None,
    send_task: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """``story_video_batch_generate`` 任务的 async runner。

    流程：
        1. 用 :class:`BatchGenerationRequest` 校验 ``run_args``；任何字段
           缺失 / 越界都会在此处抛 ``ValidationError``；
        2. 在私有 :class:`AsyncSession` 内：
           a. 把当前批量任务置 ``running`` + 进度 5；
           b. 对每个 variant 落 ``story_script_generate`` 子任务行；
           c. 通过 ``celery_app.send_task`` 投递到 ``fast`` 队列；
           d. 把所有子任务 ID 写入当前任务的 ``result``；
           e. 进度写 100、状态置 ``succeeded``、commit 一次。
        3. 异常时回滚事务，开新会话写 ``failed`` 状态 + ``error`` 字段。

    入参 (``run_args``)：
        与 :class:`BatchGenerationRequest` 字段一致，参见该模型 docstring。

    返回:
        ``{"batch_id", "child_task_ids", "variant_count", "status"}``，
        其中 ``status`` 固定为 ``"enqueued"``，方便前端任务面板上「批量
        任务自身已成功 + 子任务陆续推进」两阶段展示。

    参数:
        task_id: 当前批量任务的 ``GenerationTask.id``，会作为子任务
            ``payload['parent_batch_id']`` 的反查键。
        run_args: ``BatchGenerationRequest`` 序列化后的 dict。
        session_factory: 测试可注入；默认 :func:`async_session_maker`。
        send_task: 测试可注入 mock；默认 :data:`celery_app.send_task`。
    """
    request = BatchGenerationRequest.model_validate(run_args)

    factory = session_factory if session_factory is not None else async_session_maker
    chosen_send_task = send_task if send_task is not None else celery_app.send_task

    async with factory() as session:
        try:
            store = SqlAlchemyTaskStore(session)
            await store.set_status(task_id, TaskStatus.running)
            await store.set_progress(task_id, _RUNNING_PROGRESS)
            await session.commit()
            log_task_event(TASK_KIND, task_id, "running")

            child_task_ids = await _persist_and_dispatch_children(
                session,
                request=request,
                parent_batch_id=task_id,
                send_task=chosen_send_task,
            )

            payload: dict[str, Any] = {
                "batch_id": task_id,
                "child_task_ids": child_task_ids,
                "variant_count": len(child_task_ids),
                "status": "enqueued",
            }
            await store.set_result(task_id, payload)
            await store.set_progress(task_id, _SUCCEEDED_PROGRESS)
            await store.set_status(task_id, TaskStatus.succeeded)
            await session.commit()
            log_task_event(
                TASK_KIND,
                task_id,
                "succeeded",
                variant_count=len(child_task_ids),
            )
            return payload
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            async with async_session_maker() as failure_session:
                fail_store = SqlAlchemyTaskStore(failure_session)
                await fail_store.set_error(task_id, str(exc))
                await fail_store.set_status(task_id, TaskStatus.failed)
                await failure_session.commit()
            log_task_failure(TASK_KIND, task_id, str(exc))
            raise


def build_story_video_batch_generate_executor() -> AbstractAsyncDelegatingExecutor:
    """构造与 :data:`task_executor_registry` 兼容的执行器实例。

    存在原因：
        把构造逻辑集中到工厂函数，便于
        :mod:`app.services.worker.task_registry` 一行 ``register(...)``
        完成接入；同时让单测能直接断言 ``task_kind`` 与
        ``timeout_seconds`` 默认值，而无需依赖全局注册表的副作用。

    实现细节：
        :class:`AbstractAsyncDelegatingExecutor` 期望 runner 返回
        ``Awaitable[None]``；本 worker 的 runner 返回 dict 以便测试
        断言，因此通过薄 adapter ``_bridge_runner`` 丢弃返回值，让类型
        契约对齐，子任务结果通过 worker store 在生产环境落到
        ``GenerationTask.result``。
    """

    async def _bridge_runner(task_id: str, run_args: dict[str, Any]) -> None:
        """适配返回 ``None`` 的 worker bridge 协议。"""
        await run_story_video_batch_generate_task(task_id, run_args)

    return AbstractAsyncDelegatingExecutor(
        task_kind=TASK_KIND,
        runner=_bridge_runner,
        timeout_seconds=DEFAULT_TIMEOUT_SEC,
    )


__all__ = [
    "CELERY_ENTRY_TASK",
    "CHILD_QUEUE",
    "CHILD_TASK_KIND",
    "DEFAULT_QUEUE",
    "DEFAULT_TIMEOUT_SEC",
    "TASK_KIND",
    "build_story_video_batch_generate_executor",
    "run_story_video_batch_generate_task",
]
