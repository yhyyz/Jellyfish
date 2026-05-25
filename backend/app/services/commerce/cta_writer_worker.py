"""Worker —— ``cta_writer`` 任务执行器（W12-T4 P2）。

封装 :class:`CTAWriterAgent`（W12-T2），对**已存在**的
:class:`StoryVariant` 重写 ``cta_text`` 文本（in-place patch），
而不是创建新的 variant 行。

职责边界（与 W12-T2 ``CTAWriterAgent`` 互补）：

- Agent 层只关心“给定 LLM + ``CTAWriteVars``，怎样产出 ``CTAText``”；
- 本 worker 层负责：
  1. 从 ``run_args`` 取出 ``variant_id`` / ``pattern_id`` / ``hardness`` /
     ``urgency_type`` / ``product_name`` / ``product_url`` /
     ``discount_text`` / ``target_action``；
  2. 在私有 async session 内构造 LLM 与 Agent；
  3. 调用 :meth:`CTAWriterAgent.a_write_cta`；
  4. 把生成的 ``cta_text`` 直接写回
     ``StoryVariant.script_breakdown["cta_text"]``，其余字段保持原值；
  5. 沿用既有 task store API 维护 ``running``/``succeeded``/``failed``
     状态以及 ``progress`` 进度，与 W5-T1 ``product_info_extract_worker``
     的 session/status/error 模式保持一致。

设计要点：

- 与 :mod:`hook_writer_worker` 同形：JSON 列必须整体回赋值才能触发
  SQLAlchemy 的脏检查，本模块通过 ``dict(...)`` 浅拷贝并重新赋值
  ``script_breakdown``，确保 ``cta_text`` 真正被持久化。
- 默认超时 120s：CTA 文案的 prompt 与单次 LLM 调用更轻量，对齐
  plan ``cta_writer`` task_kind 的目标 SLA，比 hook_writer 更短。
"""

from __future__ import annotations

from typing import Any

from app.chains.agents.commerce.cta_writer_agent import CTAWriterAgent
from app.core.contracts.story import CTAText, CTAWriteVars
from app.core.db import async_session_maker
from app.core.task_manager import SqlAlchemyTaskStore
from app.core.task_manager.types import TaskStatus
from app.models.story_formula import StoryVariant
from app.services.llm.runtime import build_default_text_llm_sync
from app.services.worker.async_task_support import cancel_if_requested_async
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_logging import log_task_event, log_task_failure


TASK_KIND = "cta_writer"
"""注册键：与 plan ``task_kind`` 表保持一致，避免业务侧出现拼写漂移。"""

DEFAULT_TIMEOUT_SEC = 120.0
"""默认超时（秒）：CTA 文案 LLM 调用比钩子更轻量，2 分钟覆盖正常范围。"""

_RUNNING_PROGRESS = 10
"""进入 running 时的初始进度，与 W5-T1 ``product_info_extract`` 取值一致。"""

_SUCCEEDED_PROGRESS = 100
"""任务成功完成时的最终进度。"""


def _coerce_optional_str(value: object) -> str | None:
    """把 ``run_args`` 中的可选字符串字段归一化。

    存在原因：
        Celery 序列化路径会把缺失值变成 ``None``，但前端有时会传入
        空字符串作为占位。本函数把 ``None`` / 空串统一映射为 ``None``，
        与 :class:`CTAWriteVars` 的可选字段语义对齐。
    """
    if value in (None, ""):
        return None
    return str(value)


def _build_cta_vars(run_args: dict[str, Any]) -> CTAWriteVars:
    """从 ``run_args`` 抽取并构造 :class:`CTAWriteVars`。

    存在原因：
        把 “run_args 字段 -> Pydantic”这一步集中到一个函数里，便于
        单元测试独立断言“缺字段 -> 明确错误”与“合法字段 -> 真实
        :class:`CTAWriteVars` 实例”两条路径。

    异常:
        ``ValueError``：当任一必填字段缺失或为空字符串时抛出。
    """
    pattern_id = str(run_args.get("pattern_id") or "").strip()
    if not pattern_id:
        raise ValueError("cta_writer requires non-empty pattern_id in run_args")
    hardness = str(run_args.get("hardness") or "").strip()
    if not hardness:
        raise ValueError("cta_writer requires non-empty hardness in run_args")
    urgency_type = str(run_args.get("urgency_type") or "").strip()
    if not urgency_type:
        raise ValueError("cta_writer requires non-empty urgency_type in run_args")
    product_name = str(run_args.get("product_name") or "").strip()
    if not product_name:
        raise ValueError("cta_writer requires non-empty product_name in run_args")

    target_action_raw = run_args.get("target_action")
    target_action = (
        str(target_action_raw).strip()
        if isinstance(target_action_raw, str) and target_action_raw.strip()
        else "加购"
    )

    return CTAWriteVars(
        pattern_id=pattern_id,
        hardness=hardness,
        urgency_type=urgency_type,
        product_name=product_name,
        product_url=_coerce_optional_str(run_args.get("product_url")),
        discount_text=_coerce_optional_str(run_args.get("discount_text")),
        target_action=target_action,
    )


def _patch_variant_cta_text(variant: StoryVariant, cta_text: str) -> None:
    """在 :class:`StoryVariant` 上原地写回 ``cta_text`` 文本。

    与 :func:`hook_writer_worker._patch_variant_opening_hook` 同形：
    JSON 列在 SQLAlchemy 中默认无法自动检测“dict 内部被原地修改”，必须
    整体重新赋值列才能触发脏检查与 UPDATE。本函数：

    1. 把当前 ``script_breakdown`` 浅拷贝成新的 ``dict``；
    2. 写入 ``cta_text`` 字段；
    3. 整体赋值回 ``variant.script_breakdown``，让 ORM 检测变更。

    其他字段（如 ``opening_hook`` / ``shots`` / ``brand_mention_count``）
    保持原值，只改 CTA 文本，不影响下游消费。
    """
    breakdown = dict(variant.script_breakdown or {})
    breakdown["cta_text"] = cta_text
    variant.script_breakdown = breakdown


def _build_result_payload(variant_id: str, cta: CTAText) -> dict[str, Any]:
    """把 :class:`CTAText` 扁平化为 worker ``set_result`` 用的 dict。

    任务中心只展示通用任务信息，因此这里 payload 故意保持精简：仅暴露
    业务回追所需的字段（``variant_id`` 用于反查 variant，``cta_text``
    与 pattern 元数据让前端任务面板"一眼看完"成功结果）。
    """
    return {
        "variant_id": variant_id,
        "cta_text": cta.cta_text,
        "pattern_id": cta.pattern_id,
        "hardness": cta.hardness,
        "urgency_type": cta.urgency_type,
    }


async def run_cta_writer_task(
    task_id: str,
    run_args: dict[str, Any],
) -> None:
    """``cta_writer`` 任务的 async runner。

    流程（与 W5-T1 ``product_info_extract_worker`` 同形）：
        1. 进入 ``running`` 状态、写初始进度；
        2. 校验 ``variant_id``，构造 :class:`CTAWriteVars`；
        3. 检查取消请求；
        4. 在同步会话内构造 LLM、再异步加载 :class:`StoryVariant`；
        5. 调用 :meth:`CTAWriterAgent.a_write_cta`；
        6. 原地 patch ``variant.script_breakdown["cta_text"]``；
        7. 写 result + 进度 100% + 状态 ``succeeded``。

    任何阶段抛异常都会回滚当前事务，并以 ``failed`` 状态记录 ``error``，
    与既有 :func:`run_product_info_extract_task` 的失败收尾路径保持一致。

    入参 (``run_args``):
        - ``variant_id`` (str, required): 目标 :class:`StoryVariant.id`；
        - ``pattern_id`` (str, required): 选用的 cta_pattern.id；
        - ``hardness`` (str, required): soft / medium / hard；
        - ``urgency_type`` (str, required): scarcity / urgency / social_proof / ...；
        - ``product_name`` (str, required);
        - ``product_url`` (str, optional);
        - ``discount_text`` (str, optional);
        - ``target_action`` (str, optional, 默认 "加购")。

    输出（写入 ``task_store.set_result`` 的 dict）:
        ``{"variant_id", "cta_text", "pattern_id", "hardness", "urgency_type"}``
    """
    variant_id = str(run_args.get("variant_id") or "").strip()
    if not variant_id:
        # 故意提前 raise：避免向 LLM 发出无意义的请求。
        raise ValueError("cta_writer requires non-empty variant_id in run_args")

    cta_vars = _build_cta_vars(run_args)

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

            variant = await session.get(StoryVariant, variant_id)
            if variant is None:
                raise ValueError(f"StoryVariant not found: {variant_id}")

            llm = await session.run_sync(
                lambda sync_db: build_default_text_llm_sync(sync_db, thinking=False)
            )
            agent = CTAWriterAgent(llm)
            result = await agent.a_write_cta(vars=cta_vars)

            if await cancel_if_requested_async(store=store, task_id=task_id, session=session):
                log_task_event(TASK_KIND, task_id, "cancelled", stage="after_execute")
                return

            _patch_variant_cta_text(variant, result.cta_text)

            payload = _build_result_payload(variant_id, result)
            await store.set_result(task_id, payload)
            await store.set_progress(task_id, _SUCCEEDED_PROGRESS)
            await store.set_status(task_id, TaskStatus.succeeded)
            await session.commit()
            log_task_event(TASK_KIND, task_id, "succeeded", variant_id=variant_id)
        except Exception as exc:  # noqa: BLE001
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


def build_cta_writer_executor() -> AbstractAsyncDelegatingExecutor:
    """构造与 ``task_executor_registry`` 兼容的执行器实例。

    存在原因：
        把构造逻辑集中到工厂函数，便于 ``task_registry.py`` 一行
        ``register(...)`` 完成接入；同时让单测能直接断言
        ``task_kind`` 与 ``timeout_seconds`` 等默认值，
        而无需依赖全局注册表的副作用。

    返回:
        预配置的 :class:`AbstractAsyncDelegatingExecutor`，其
        ``task_kind`` 为 :data:`TASK_KIND`，
        ``timeout_seconds`` 为 :data:`DEFAULT_TIMEOUT_SEC`。
    """
    return AbstractAsyncDelegatingExecutor(
        task_kind=TASK_KIND,
        runner=run_cta_writer_task,
        timeout_seconds=DEFAULT_TIMEOUT_SEC,
    )


__all__ = [
    "DEFAULT_TIMEOUT_SEC",
    "TASK_KIND",
    "build_cta_writer_executor",
    "run_cta_writer_task",
]
