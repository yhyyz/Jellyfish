"""voice_clone_poll worker（P5 W29 引入）。

为什么存在：
    DashScope ``create_voice`` 是异步训练，调用即返回 voice_id 但状态停留
    在 ``DEPLOYING``，需要前端 / 后端持续轮询 ``query_voice`` 直到状态变成
    ``OK`` / ``UNDEPLOYED`` 才能让 VoicePack 可被 TTS 合成路径选用。

    把"轮询 + 状态翻译 + DB 行更新"封装成异步任务而非前端长轮询：

    - 前端只需要刷新自己关心的 VoicePack 行；
    - 失败重试 / 超时 / 中途 cancel 都走任务系统统一管线；
    - 不依赖 HTTP 请求生命周期，浏览器关掉也能继续完成训练。

设计要点：
    - task_kind = ``voice_clone_poll``，注册到 ``fast`` 队列（轮询不是大计
      算，与 commerce/* 单任务对齐）。
    - 默认超时 ``600s``，覆盖 ``max_attempts=30 × poll_interval=10s = 300s``
      训练耗时 + 余量。
    - run_args 仅含 ``voice_pack_id``：worker 启动后从 :class:`VoicePack` 行
      读 ``provider_voice_id`` / ``region``，确保单一可信源。
    - 每轮 query 之间 ``asyncio.sleep(POLL_INTERVAL_SEC)``；不在循环里持有
      session，避免长事务。每次 commit 后再重新 ``session.get`` 拿最新行。
    - W19b 契约：失败 / 成功 / 超时三类终态都先 commit DB 再 ``store.set_*``，
      让 worker 失败时 :class:`VoicePack` 行也能保持一致。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.core.db import async_session_maker
from app.core.task_manager import SqlAlchemyTaskStore
from app.core.task_manager.types import TaskStatus
from app.models.types import VoiceCloneStatus, VoiceRegion
from app.models.voice_pack import VoicePack
from app.services.studio.voice_clone_service import query_clone_status
from app.services.worker.async_task_support import cancel_if_requested_async
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_logging import log_task_event, log_task_failure


logger = logging.getLogger(__name__)


TASK_KIND = "voice_clone_poll"
"""注册键：与 :class:`CommerceTaskDispatchService.enqueue_voice_clone_poll` 同步。"""

DEFAULT_TIMEOUT_SECONDS = 600.0
"""默认超时：30 次轮询 × 10s + 上传 / DB / SDK 余量。"""

POLL_INTERVAL_SEC = 10.0
"""每两次 query_voice 之间的等待时长（秒）。"""

MAX_ATTEMPTS = 30
"""最多轮询次数；30 × 10s = 300s 等于 DashScope 官方训练上限。"""

_RUNNING_PROGRESS = 5
_POLL_BASE_PROGRESS = 10
_POLL_MAX_PROGRESS = 90
_SUCCEEDED_PROGRESS = 100


def _coerce_str(value: object, *, default: str = "") -> str:
    """把 ``run_args`` 中的字符串字段安全规范化（去首尾空白）。"""
    if value is None:
        return default
    return str(value).strip() or default


def _utcnow_naive() -> datetime:
    """返回 UTC 无 tz datetime，与 ORM ``DateTime(timezone=True)`` 跨后端兼容。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _resolve_region(raw: object) -> VoiceRegion:
    """把 ORM 列里取出的 ``region`` 字符串还原为枚举。

    SQLite 把 String 列以 str 返回；MySQL 在 native_enum 下可能直接返回枚举。
    统一这里做兼容；解析失败回退到北京端点（与 P5 默认推荐一致）。
    """
    if isinstance(raw, VoiceRegion):
        return raw
    try:
        return VoiceRegion(str(raw))
    except ValueError:
        logger.warning("unknown region value %r; fallback to cn-beijing", raw)
        return VoiceRegion.cn_beijing


async def run_voice_clone_poll_task(
    task_id: str,
    run_args: dict[str, Any],
) -> None:
    """异步 runner：轮询 DashScope ``query_voice`` 直至终态，并把结果写回 VoicePack 行。

    输入 (``run_args``):
        - ``voice_pack_id`` (str, required): :class:`VoicePack` 主键，
          worker 内部据此读 ``provider_voice_id`` / ``region``。

    输出（写入 ``store.set_result`` 的 dict）：
        ``{voice_pack_id, clone_status, provider_voice_id?, failure_reason?, cloned_at?}``。

    行为：
        1. set_status(running) + commit
        2. 循环最多 ``MAX_ATTEMPTS`` 次：
           - cancel check
           - ``query_clone_status``
           - ``ready`` -> 写 VoicePack: clone_status=ready / cloned_at=now() -> commit -> 退出循环
           - ``failed`` -> 写 VoicePack: clone_status=failed / description 末尾追加失败原因 -> commit -> 退出
           - ``deploying`` -> ``asyncio.sleep(POLL_INTERVAL_SEC)`` 后继续
        3. 循环结束仍未拿到终态 -> 视为超时，VoicePack: clone_status=failed
        4. set_result + set_status(succeeded) / failed

    异常处理：
        - ``query_voice`` 抛异常时由 :func:`query_clone_status` 内部捕获翻译为
          ``failed``；不会抛到本 runner。
        - 本 runner 自身仅捕获最外层意外异常并落 failed 状态，避免 worker 崩溃。
    """

    voice_pack_id = _coerce_str(run_args.get("voice_pack_id"))
    if not voice_pack_id:
        raise ValueError("voice_clone_poll requires voice_pack_id in run_args")

    async with async_session_maker() as session:
        try:
            store = SqlAlchemyTaskStore(session)
            await store.set_status(task_id, TaskStatus.running)
            await store.set_progress(task_id, _RUNNING_PROGRESS)
            await session.commit()
            log_task_event(TASK_KIND, task_id, "running")

            voice_pack = await session.get(VoicePack, voice_pack_id)
            if voice_pack is None:
                raise LookupError(
                    f"voice_pack not found: voice_pack_id={voice_pack_id}"
                )
            voice_id = voice_pack.provider_voice_id
            region = _resolve_region(voice_pack.region)

            terminal_status: VoiceCloneStatus | None = None
            failure_reason: str | None = None

            for attempt in range(MAX_ATTEMPTS):
                if await cancel_if_requested_async(
                    store=store, task_id=task_id, session=session
                ):
                    log_task_event(
                        TASK_KIND, task_id, "cancelled", attempt=attempt
                    )
                    return

                status, reason = await query_clone_status(
                    voice_id=voice_id, region=region
                )

                if status == VoiceCloneStatus.ready:
                    terminal_status = status
                    break
                if status == VoiceCloneStatus.failed:
                    terminal_status = status
                    failure_reason = reason
                    break

                # deploying -> 进度推进 + 等待下一轮
                progress = min(
                    _POLL_BASE_PROGRESS
                    + int(
                        (_POLL_MAX_PROGRESS - _POLL_BASE_PROGRESS)
                        * (attempt + 1)
                        / MAX_ATTEMPTS
                    ),
                    _POLL_MAX_PROGRESS,
                )
                await store.set_progress(task_id, progress)
                await session.commit()
                await asyncio.sleep(POLL_INTERVAL_SEC)

            if terminal_status is None:
                terminal_status = VoiceCloneStatus.failed
                failure_reason = (
                    f"voice_clone_poll timed out after {MAX_ATTEMPTS} attempts"
                )

            voice_pack = await session.get(VoicePack, voice_pack_id)
            if voice_pack is None:
                raise LookupError(
                    f"voice_pack vanished mid-poll: voice_pack_id={voice_pack_id}"
                )

            voice_pack.clone_status = terminal_status
            if terminal_status == VoiceCloneStatus.ready:
                voice_pack.cloned_at = _utcnow_naive()
            elif terminal_status == VoiceCloneStatus.failed:
                voice_pack.cloned_at = None
                if failure_reason:
                    suffix = f"\n[clone_failed] {failure_reason}"
                    if not (voice_pack.description or "").endswith(suffix):
                        voice_pack.description = (
                            voice_pack.description or ""
                        ) + suffix

            result_payload: dict[str, Any] = {
                "voice_pack_id": voice_pack_id,
                "clone_status": terminal_status.value,
                "provider_voice_id": voice_pack.provider_voice_id,
                "failure_reason": failure_reason,
                "cloned_at": (
                    voice_pack.cloned_at.isoformat()
                    if voice_pack.cloned_at is not None
                    else None
                ),
            }

            await store.set_result(task_id, result_payload)
            await store.set_progress(task_id, _SUCCEEDED_PROGRESS)
            await store.set_status(task_id, TaskStatus.succeeded)
            await session.commit()
            log_task_event(
                TASK_KIND,
                task_id,
                "succeeded",
                terminal_status=terminal_status.value,
            )
        except Exception as exc:  # noqa: BLE001 - 与既有 worker 模板保持一致
            await session.rollback()
            async with async_session_maker() as failure_session:
                fail_store = SqlAlchemyTaskStore(failure_session)
                await fail_store.set_error(task_id, str(exc))
                await fail_store.set_status(task_id, TaskStatus.failed)
                await failure_session.commit()
            log_task_failure(TASK_KIND, task_id, str(exc))
            raise


def build_voice_clone_poll_executor() -> AbstractAsyncDelegatingExecutor:
    """构造与 ``task_executor_registry`` 兼容的 voice_clone_poll 执行器实例。

    存在原因：
        把构造逻辑收敛到工厂函数，便于 ``task_registry.py`` 一行 register
        完成接入；同时让单测能直接断言 ``task_kind`` / ``timeout_seconds``
        等默认值，而无需依赖全局注册表的副作用。
    """

    return AbstractAsyncDelegatingExecutor(
        task_kind=TASK_KIND,
        runner=run_voice_clone_poll_task,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
    )


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_ATTEMPTS",
    "POLL_INTERVAL_SEC",
    "TASK_KIND",
    "build_voice_clone_poll_executor",
    "run_voice_clone_poll_task",
]
