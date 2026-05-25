"""Commerce worker — ``product_info_extract`` 任务执行器。

将 :class:`ProductExtractorAgent` 包装为一个可被
:data:`task_executor_registry` 解析的 ``AbstractAsyncDelegatingExecutor``，
形成统一的 worker 执行入口。

职责边界（与 W4-T1 ``ProductExtractorAgent`` 保持互补）：

- Agent 层只关心“给定 LLM 与 prompt，怎样产出 ``ProductExtractionResult``”；
- 本 worker 层负责：
  1. 从 ``GenerationTask.payload['run_args']`` 取出 ``raw_text`` /
     ``target_fields``；
  2. 在 worker 私有 async 会话中构造 LLM 与 Agent；
  3. 调用 :meth:`ProductExtractorAgent.a_extract_product` 完成抽取；
  4. 将 ``ProductExtractionResult`` 通过
     ``model_dump(mode="json")`` 序列化为 dict 写回任务结果；
  5. 沿用既有 task store API 维护 ``running``/``succeeded``/``failed``
     状态以及 ``progress`` 进度；

设计要点：

- 选择 :class:`AbstractAsyncDelegatingExecutor` 而非自定义同步
  ``AbstractWorkerTaskExecutor`` 子类，理由在于：
  ``ProductExtractorAgent.a_extract_product`` 是 ``async``，与图片
  生成 / 分镜帧提示词 / 章节时间线导出等既有异步任务保持一致的执行模板，
  避免重复实现 `asyncio.run` / 取消检测 / 超时收敛等样板逻辑。
- 默认超时 ``300s``，对齐 P2 Plan ``task_kind`` 表中关于
  ``product_info_extract`` 的目标 SLA（fast 队列 + 5 分钟硬上限）。
"""

from __future__ import annotations

from typing import Any

from app.chains.agents.commerce.product_extractor_agent import ProductExtractorAgent
from app.core.db import async_session_maker
from app.core.task_manager import SqlAlchemyTaskStore
from app.core.task_manager.types import TaskStatus
from app.services.llm.runtime import build_default_text_llm_sync
from app.services.worker.async_task_support import cancel_if_requested_async
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_logging import log_task_event, log_task_failure


TASK_KIND = "product_info_extract"
"""注册键：与 plan ``task_kind`` 表保持一致，避免业务侧出现拼写漂移。"""

DEFAULT_TIMEOUT_SECONDS = 300.0
"""默认超时（秒）：对齐 P2 plan 中 ``product_info_extract`` 的 SLA。"""

_RUNNING_PROGRESS = 10
"""进入 running 时的初始进度，参考 image_generation 任务的取值。"""

_SUCCEEDED_PROGRESS = 100
"""任务成功完成时的最终进度。"""


def _coerce_target_fields(value: object) -> list[str] | None:
    """将 ``run_args['target_fields']`` 规范化为 ``list[str] | None``。

    存在原因：
        ``GenerationTask.payload`` 来自上游 API/任务创建端，类型并不严格，
        worker 必须在执行前做一次安全的归一化，避免把 ``""`` / 非列表值
        透传到 Agent 后才暴露错误。

    规则：
        - ``None`` / 不存在 → ``None``（让 Agent 走“抽全部字段”分支）；
        - 字符串列表 → 去除空白后非空项；空列表则视作 ``None``；
        - 其他类型 → ``None``，与缺省路径一致，保持向前兼容。
    """
    if value is None:
        return None
    if not isinstance(value, list):
        return None
    cleaned: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            cleaned.append(text)
    return cleaned or None


async def run_product_info_extract_task(
    task_id: str,
    run_args: dict[str, Any],
) -> None:
    """异步 runner：抽取商品信息并把结果写回任务存储。

    输入 (``run_args``):
        - ``raw_text`` (str, required): 商品页文本或 URL。
        - ``target_fields`` (list[str] | None): 期望抽取的字段子集，
          为 ``None`` 时让 Agent 抽取全部字段。

    输出（写入 ``task_store.set_result`` 的 dict）:
        ``ProductExtractionResult.model_dump(mode="json")``，包含
        ``name``、``brand``、``category``、``description``、
        ``price_anchor``、``sku``、``selling_points``、
        ``pain_points_solved``、``target_audience``、``catchphrases``、
        ``competitor_names``、``health_disclaimer_required`` 等字段。

    异常处理：
        与既有 async runner（如 ``run_image_generation_task``）保持一致：
        本函数自身只在外层 ``try`` 中负责 rollback、写错误信息、置 failed；
        ``AbstractAsyncDelegatingExecutor`` 仍会在外层捕获并重新抛出，
        以便 Celery 进入失败状态。
    """
    raw_text = str(run_args.get("raw_text") or "").strip()
    if not raw_text:
        # 故意提前 raise：保持错误尽早暴露，避免无意义的 LLM 调用。
        raise ValueError("product_info_extract requires non-empty raw_text in run_args")

    target_fields = _coerce_target_fields(run_args.get("target_fields"))

    async with async_session_maker() as session:
        try:
            store = SqlAlchemyTaskStore(session)
            await store.set_status(task_id, TaskStatus.running)
            await store.set_progress(task_id, _RUNNING_PROGRESS)
            await session.commit()
            log_task_event(TASK_KIND, task_id, "running")

            if await cancel_if_requested_async(store=store, task_id=task_id, session=session):
                log_task_event(TASK_KIND, task_id, "cancelled", stage="before_execute")
                return

            # 在 async 会话内通过 ``run_sync`` 桥接到同步 LLM 工厂，
            # 与 ``run_shot_frame_prompt_task`` 等既有 async runner 保持一致。
            llm = await session.run_sync(
                lambda sync_db: build_default_text_llm_sync(sync_db, thinking=False)
            )
            agent = ProductExtractorAgent(llm)
            result = await agent.a_extract_product(
                raw_text=raw_text,
                target_fields=target_fields,
            )

            if await cancel_if_requested_async(store=store, task_id=task_id, session=session):
                log_task_event(TASK_KIND, task_id, "cancelled", stage="after_execute")
                return

            # ``mode="json"`` 保证结果是纯 JSON 兼容的基础类型，
            # 便于直接写入任务存储与跨进程序列化。
            result_payload = result.model_dump(mode="json")
            await store.set_result(task_id, result_payload)
            await store.set_progress(task_id, _SUCCEEDED_PROGRESS)
            await store.set_status(task_id, TaskStatus.succeeded)
            await session.commit()
            log_task_event(TASK_KIND, task_id, "succeeded")
        except Exception as exc:  # noqa: BLE001
            # 一旦本次 session 已经写入半截状态，先 rollback；再用独立会话写
            # 失败状态，避免“失败回写本身因为脏会话再次抛错”的连锁问题。
            await session.rollback()
            async with async_session_maker() as failure_session:
                fail_store = SqlAlchemyTaskStore(failure_session)
                await fail_store.set_error(task_id, str(exc))
                await fail_store.set_status(task_id, TaskStatus.failed)
                await failure_session.commit()
            log_task_failure(TASK_KIND, task_id, str(exc))
            raise


# ---------------------------------------------------------------------------
# Executor 工厂（供 ``task_executor_registry`` 注册使用）
# ---------------------------------------------------------------------------


def build_product_info_extract_executor() -> AbstractAsyncDelegatingExecutor:
    """构造与 ``task_executor_registry`` 兼容的执行器实例。

    存在原因：
        把构造逻辑集中到工厂函数，便于 ``task_registry.py`` 一行
        ``register(...)`` 完成接入；同时让单测能直接断言
        ``task_kind`` 与 ``timeout_seconds`` 等默认值，
        而无需依赖全局注册表的副作用。

    返回:
        预配置的 :class:`AbstractAsyncDelegatingExecutor`，其
        ``task_kind`` 为 :data:`TASK_KIND`，
        ``timeout_seconds`` 为 :data:`DEFAULT_TIMEOUT_SECONDS`。
    """
    return AbstractAsyncDelegatingExecutor(
        task_kind=TASK_KIND,
        runner=run_product_info_extract_task,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
    )


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "TASK_KIND",
    "build_product_info_extract_executor",
    "run_product_info_extract_task",
]
