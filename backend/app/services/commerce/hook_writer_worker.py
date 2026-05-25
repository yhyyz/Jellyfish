"""Worker —— ``hook_writer`` 任务执行器（W12-T4 P2）。

封装 :class:`HookWriterAgent`（W12-T1），对**已存在**的
:class:`StoryVariant` 重写 ``opening_hook`` 文本（in-place patch），
而不是创建新的 variant 行。

职责边界（与 W12-T1 ``HookWriterAgent`` 互补）：

- Agent 层只关心“给定 LLM + ``HookWriteVars``，怎样产出 ``ShotHook``”；
- 本 worker 层负责：
  1. 从 ``run_args`` 取出 ``variant_id`` / ``pattern_id`` / ``pattern_type``
     与商品 / 受众上下文；
  2. 在私有 async session 内构造 LLM 与 Agent；
  3. 调用 :meth:`HookWriterAgent.a_write_hook`；
  4. 把生成的 ``hook_text`` 直接写回
     ``StoryVariant.script_breakdown["opening_hook"]``，其余字段保持原值；
  5. 沿用既有 task store API 维护 ``running``/``succeeded``/``failed``
     状态以及 ``progress`` 进度，与 W5-T1 ``product_info_extract_worker``
     的 session/status/error 模式保持一致。

设计要点：

- ``script_breakdown`` 是 JSON 列（``Mapped[dict[str, Any]]``），SQLAlchemy
  对“原 dict 内字段被原地修改”不会自动 dirty 标记，因此本 worker 显式
  做 ``dict(...)`` 浅拷贝并整体回赋值，确保 ORM 把列写回 DB。
- 默认超时 180s：钩子生成的提示词与单次 LLM 调用为主，对齐 plan
  ``hook_writer`` task_kind 在 P2 中作为快队列任务的目标 SLA。
"""

from __future__ import annotations

from typing import Any

from app.chains.agents.commerce.hook_writer_agent import HookWriterAgent
from app.core.contracts.story import HookWriteVars, ShotHook
from app.core.db import async_session_maker
from app.core.task_manager import SqlAlchemyTaskStore
from app.core.task_manager.types import TaskStatus
from app.models.story_formula import StoryVariant
from app.services.llm.runtime import build_default_text_llm_sync
from app.services.worker.async_task_support import cancel_if_requested_async
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_logging import log_task_event, log_task_failure


TASK_KIND = "hook_writer"
"""注册键：与 plan ``task_kind`` 表保持一致，避免业务侧出现拼写漂移。"""

DEFAULT_TIMEOUT_SEC = 180.0
"""默认超时（秒）：对齐 P2 plan ``hook_writer`` 在 fast 队列下的 SLA。"""

_RUNNING_PROGRESS = 10
"""进入 running 时的初始进度，与 W5-T1 ``product_info_extract`` 取值一致。"""

_SUCCEEDED_PROGRESS = 100
"""任务成功完成时的最终进度。"""


def _coerce_str_list(value: object) -> list[str]:
    """把 ``run_args`` 中的列表参数归一化为非空字符串列表。

    存在原因：
        ``audience_pain_points`` 来自调度层，类型不严格；JSON 序列化路径可能
        把缺失值变成 ``None`` 或非 list 类型。统一做一次防御性归一化，避免
        把脏数据透传到 :class:`HookWriteVars` 后才暴露 ``ValidationError``。
    """
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            cleaned.append(text)
    return cleaned


def _coerce_demographics(value: object) -> dict[str, Any]:
    """把 ``audience_demographics`` 归一化为 ``dict[str, Any]``。

    与 :func:`_coerce_str_list` 的设计动机一致：调度层可能传入 ``None``
    或非 dict 值，本函数把这些情况统一规整为空 dict，让 Pydantic 默认
    工厂生效。
    """
    if not isinstance(value, dict):
        return {}
    # ``HookWriteVars.audience_demographics`` 的 key 类型为 ``str``；
    # 用 ``str(k)`` 做一次防御性转换，避免上游意外传入非字符串 key。
    return {str(k): v for k, v in value.items()}


def _build_hook_vars(run_args: dict[str, Any]) -> HookWriteVars:
    """从 ``run_args`` 抽取并构造 :class:`HookWriteVars`。

    存在原因：
        把 “run_args 字段 -> Pydantic”这一步集中到一个函数里，便于
        单元测试独立断言“缺字段 -> 明确错误”与“合法字段 -> 真实
        :class:`HookWriteVars` 实例”两条路径。

    异常:
        ``ValueError``：当任一必填字段缺失或为空字符串时抛出。
    """
    pattern_id = str(run_args.get("pattern_id") or "").strip()
    if not pattern_id:
        raise ValueError("hook_writer requires non-empty pattern_id in run_args")
    pattern_type = str(run_args.get("pattern_type") or "").strip()
    if not pattern_type:
        raise ValueError("hook_writer requires non-empty pattern_type in run_args")
    product_name = str(run_args.get("product_name") or "").strip()
    if not product_name:
        raise ValueError("hook_writer requires non-empty product_name in run_args")

    product_description_raw = run_args.get("product_description")
    product_description: str | None
    if product_description_raw in (None, ""):
        product_description = None
    else:
        product_description = str(product_description_raw)

    return HookWriteVars(
        pattern_id=pattern_id,
        pattern_type=pattern_type,
        product_name=product_name,
        product_description=product_description,
        audience_pain_points=_coerce_str_list(run_args.get("audience_pain_points")),
        audience_demographics=_coerce_demographics(run_args.get("audience_demographics")),
    )


def _patch_variant_opening_hook(variant: StoryVariant, hook_text: str) -> None:
    """在 :class:`StoryVariant` 上原地写回 ``opening_hook`` 文本。

    JSON 列在 SQLAlchemy 中默认无法自动检测“dict 内部被原地修改”，
    必须整体重新赋值列才能触发脏检查与 UPDATE。本函数：

    1. 把当前 ``script_breakdown`` 浅拷贝成新的 ``dict``；
    2. 写入 ``opening_hook`` 字段；
    3. 整体赋值回 ``variant.script_breakdown``，让 ORM 检测变更。

    其他字段（如 ``cta_text`` / ``shots`` / ``total_shots`` 等）保持原值，
    确保只改钩子文本、不影响下游消费。
    """
    breakdown = dict(variant.script_breakdown or {})
    breakdown["opening_hook"] = hook_text
    variant.script_breakdown = breakdown


def _build_result_payload(variant_id: str, hook: ShotHook) -> dict[str, Any]:
    """把 :class:`ShotHook` 扁平化为 worker ``set_result`` 用的 dict。

    任务中心只展示通用任务信息，因此这里 payload 故意保持精简：仅暴露
    业务回追所需的字段（``variant_id`` 用于反查 variant，``hook_text``
    与 pattern 元数据让前端任务面板"一眼看完"成功结果）。
    """
    return {
        "variant_id": variant_id,
        "hook_text": hook.hook_text,
        "pattern_id": hook.pattern_id,
        "pattern_type": hook.pattern_type,
        "rationale": hook.rationale,
    }


async def run_hook_writer_task(
    task_id: str,
    run_args: dict[str, Any],
) -> None:
    """``hook_writer`` 任务的 async runner。

    流程（与 W5-T1 ``product_info_extract_worker`` 同形）：
        1. 进入 ``running`` 状态、写初始进度；
        2. 校验 ``variant_id``，构造 :class:`HookWriteVars`；
        3. 检查取消请求；
        4. 在同步会话内构造 LLM、再异步加载 :class:`StoryVariant`；
        5. 调用 :meth:`HookWriterAgent.a_write_hook`；
        6. 原地 patch ``variant.script_breakdown["opening_hook"]``；
        7. 写 result + 进度 100% + 状态 ``succeeded``。

    任何阶段抛异常都会回滚当前事务，并以 ``failed`` 状态记录 ``error``，
    与既有 :func:`run_product_info_extract_task` 的失败收尾路径保持一致。

    入参 (``run_args``):
        - ``variant_id`` (str, required): 目标 :class:`StoryVariant.id`；
        - ``pattern_id`` (str, required): 选用的 hook_pattern.id；
        - ``pattern_type`` (str, required): 钩子模式分类（question / conflict / ...）；
        - ``product_name`` (str, required);
        - ``product_description`` (str, optional);
        - ``audience_pain_points`` (list[str], optional);
        - ``audience_demographics`` (dict, optional).

    输出（写入 ``task_store.set_result`` 的 dict）:
        ``{"variant_id", "hook_text", "pattern_id", "pattern_type", "rationale"}``
    """
    variant_id = str(run_args.get("variant_id") or "").strip()
    if not variant_id:
        # 故意提前 raise：避免向 LLM 发出无意义的请求，以及向 DB 发出空查询。
        raise ValueError("hook_writer requires non-empty variant_id in run_args")

    hook_vars = _build_hook_vars(run_args)

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
                # 与 W5-T3 “variant 不存在”策略一致：以 ValueError 抛出，
                # 让外层走 ``failed`` 收尾路径并把可读错误写进 task.error。
                raise ValueError(f"StoryVariant not found: {variant_id}")

            llm = await session.run_sync(
                lambda sync_db: build_default_text_llm_sync(sync_db, thinking=False)
            )
            agent = HookWriterAgent(llm)
            result = await agent.a_write_hook(vars=hook_vars)

            if await cancel_if_requested_async(store=store, task_id=task_id, session=session):
                log_task_event(TASK_KIND, task_id, "cancelled", stage="after_execute")
                return

            _patch_variant_opening_hook(variant, result.hook_text)

            payload = _build_result_payload(variant_id, result)
            await store.set_result(task_id, payload)
            await store.set_progress(task_id, _SUCCEEDED_PROGRESS)
            await store.set_status(task_id, TaskStatus.succeeded)
            await session.commit()
            log_task_event(TASK_KIND, task_id, "succeeded", variant_id=variant_id)
        except Exception as exc:  # noqa: BLE001
            # 一旦本 session 写过半截状态，先 rollback；再用独立 session 写
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


def build_hook_writer_executor() -> AbstractAsyncDelegatingExecutor:
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
        runner=run_hook_writer_task,
        timeout_seconds=DEFAULT_TIMEOUT_SEC,
    )


__all__ = [
    "DEFAULT_TIMEOUT_SEC",
    "TASK_KIND",
    "build_hook_writer_executor",
    "run_hook_writer_task",
]
