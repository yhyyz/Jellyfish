"""Worker —— ``archetype_rewrite`` 任务执行器（W12-T4 P2）。

封装 :class:`ArchetypeVoiceRewriterAgent`（W12-T3），按指定
``archetype`` + ``tone_grid`` 重写**已存在**的 :class:`StoryVariant`
全脚本对白与旁白文本（in-place patch），保留镜头结构。

职责边界（与 W12-T3 ``ArchetypeVoiceRewriterAgent`` 互补）：

- Agent 层只关心“给定 LLM + ``ArchetypeRewriteVars``，怎样产出
  与原脚本结构一致的 :class:`StoryScript`”，并自带结构保留与禁词校验；
- 本 worker 层负责：
  1. 从 ``run_args`` 取出 ``variant_id`` 与改写参数；
  2. 在私有 async session 内加载现有 :class:`StoryVariant`，
     从 ``script_breakdown`` 读出原始脚本；
  3. 构造 LLM 与 Agent；
  4. 调用 :meth:`ArchetypeVoiceRewriterAgent.a_rewrite_voice`；
  5. 把改写后的 :class:`StoryScript` 整体 ``model_dump(mode="json")``
     写回 ``StoryVariant.script_breakdown``；同步把
     ``StoryVariant.archetype`` 列刷新为本次目标 archetype；
  6. 沿用既有 task store API 维护 ``running``/``succeeded``/``failed``
     状态以及 ``progress`` 进度。

设计要点：

- ``script_breakdown`` 不再使用浅拷贝/局部 patch：本任务**整段重写**
  脚本（保留结构、改写文本），故直接整体回赋值。
- ``variant.archetype`` 列由 W2-T1 引入，类型为 ``String(32) | None``；
  通过本任务把 archetype 名落到 DB，方便后续 A/B 决策与展示。
- 默认超时 600s（10 分钟）：脚本级改写涉及多镜头、长上下文 LLM 调用，
  对齐 plan ``archetype_rewrite`` task_kind 的目标 SLA 上限。
"""

from __future__ import annotations

from typing import Any

from app.chains.agents.commerce.archetype_voice_rewriter_agent import (
    ArchetypeVoiceRewriterAgent,
)
from app.core.contracts.story import ArchetypeRewriteVars, StoryScript
from app.core.db import async_session_maker
from app.core.task_manager import SqlAlchemyTaskStore
from app.core.task_manager.types import TaskStatus
from app.models.story_formula import StoryVariant
from app.services.llm.runtime import build_default_text_llm_sync
from app.services.worker.async_task_support import cancel_if_requested_async
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_logging import log_task_event, log_task_failure


TASK_KIND = "archetype_rewrite"
"""注册键：与 plan ``task_kind`` 表保持一致，避免业务侧出现拼写漂移。"""

DEFAULT_TIMEOUT_SEC = 600.0
"""默认超时（秒）：全脚本改写覆盖多镜头长上下文，10 分钟硬上限。"""

_RUNNING_PROGRESS = 10
"""进入 running 时的初始进度，与 W5-T1 ``product_info_extract`` 取值一致。"""

_SUCCEEDED_PROGRESS = 100
"""任务成功完成时的最终进度。"""


def _coerce_str_list(value: object) -> list[str]:
    """把 ``run_args`` 中的字符串列表参数归一化为非空字符串列表。

    存在原因：
        ``words_to_avoid`` / ``preferred_vocab`` 来自调度层，类型不严格；
        Celery 序列化路径可能把缺失值变成 ``None`` 或非 list 类型。统一做
        一次防御性归一化，避免把脏数据透传到 :class:`ArchetypeRewriteVars`
        后才暴露 ``ValidationError``。
    """
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            cleaned.append(text)
    return cleaned


def _coerce_tone_grid(value: object) -> dict[str, int]:
    """把 ``tone_grid`` 归一化为 ``dict[str, int]``。

    :class:`ArchetypeRewriteVars.tone_grid` 类型为 ``dict[str, int]``；
    JSON 序列化后整数会被还原为 ``int``，但仍可能出现 ``float`` 或字符串
    输入。本函数对每个值做一次 ``int(...)`` 转换，失败则跳过该 key。
    """
    if not isinstance(value, dict):
        return {}
    grid: dict[str, int] = {}
    for key, raw_val in value.items():
        try:
            grid[str(key)] = int(raw_val)
        except (TypeError, ValueError):
            # 静默跳过非整数维度：避免 worker 因为单一脏字段就 fail 整个任务。
            continue
    return grid


def _build_rewrite_vars(
    run_args: dict[str, Any],
    *,
    original_script: dict[str, Any],
) -> ArchetypeRewriteVars:
    """从 ``run_args`` 构造 :class:`ArchetypeRewriteVars`。

    ``original_script`` 来自 :class:`StoryVariant.script_breakdown`，
    由调用方先从 DB 加载并以 ``dict`` 形式注入；这样 worker 入口就只
    需要 ``variant_id`` 与改写参数，不需要在 ``run_args`` 里重复传入
    完整脚本，降低 Celery 消息体积。

    异常:
        ``ValueError``：当 ``archetype`` / ``archetype_description`` 缺失。
    """
    archetype = str(run_args.get("archetype") or "").strip()
    if not archetype:
        raise ValueError(
            "archetype_rewrite requires non-empty archetype in run_args"
        )
    archetype_description = str(run_args.get("archetype_description") or "").strip()
    if not archetype_description:
        raise ValueError(
            "archetype_rewrite requires non-empty archetype_description in run_args"
        )

    return ArchetypeRewriteVars(
        original_script=original_script,
        archetype=archetype,
        archetype_description=archetype_description,
        tone_grid=_coerce_tone_grid(run_args.get("tone_grid")),
        words_to_avoid=_coerce_str_list(run_args.get("words_to_avoid")),
        preferred_vocab=_coerce_str_list(run_args.get("preferred_vocab")),
    )


def _build_result_payload(
    variant_id: str,
    archetype: str,
    rewritten: StoryScript,
) -> dict[str, Any]:
    """把改写结果扁平化为 worker ``set_result`` 用的 dict。

    任务中心只展示通用任务信息，因此这里 payload 故意保持精简：仅暴露
    业务回追所需的字段（``variant_id`` / ``archetype`` 反查变体；
    ``shot_count`` / ``brand_mention_count`` 让前端任务面板"一眼看完"
    本次改写的规模与品牌口播位变化）。
    """
    return {
        "variant_id": variant_id,
        "archetype": archetype,
        "shot_count": len(rewritten.shots),
        "brand_mention_count": rewritten.brand_mention_count,
    }


async def run_archetype_rewrite_task(
    task_id: str,
    run_args: dict[str, Any],
) -> None:
    """``archetype_rewrite`` 任务的 async runner。

    流程（与 W5-T1 ``product_info_extract_worker`` 同形）：
        1. 进入 ``running`` 状态、写初始进度；
        2. 校验 ``variant_id``；
        3. 检查取消请求；
        4. 加载 :class:`StoryVariant`，从 ``script_breakdown`` 读原始脚本；
        5. 构造 :class:`ArchetypeRewriteVars`；
        6. 在同步会话内构造 LLM；
        7. 调用 :meth:`ArchetypeVoiceRewriterAgent.a_rewrite_voice`；
        8. 把改写后的 :class:`StoryScript` 整体 ``model_dump(mode="json")``
           写回 ``variant.script_breakdown``，并刷新 ``variant.archetype``；
        9. 写 result + 进度 100% + 状态 ``succeeded``。

    任何阶段抛异常都会回滚当前事务，并以 ``failed`` 状态记录 ``error``，
    与既有 :func:`run_product_info_extract_task` 的失败收尾路径保持一致。

    入参 (``run_args``):
        - ``variant_id`` (str, required): 目标 :class:`StoryVariant.id`；
        - ``archetype`` (str, required): 12 类 ``BrandArchetype`` 之一；
        - ``archetype_description`` (str, required): 自然语言喂给 LLM；
        - ``tone_grid`` (dict[str, int], required): dimension -> 0~10；
        - ``words_to_avoid`` (list[str], optional);
        - ``preferred_vocab`` (list[str], optional)。

    输出（写入 ``task_store.set_result`` 的 dict）:
        ``{"variant_id", "archetype", "shot_count", "brand_mention_count"}``
    """
    variant_id = str(run_args.get("variant_id") or "").strip()
    if not variant_id:
        raise ValueError(
            "archetype_rewrite requires non-empty variant_id in run_args"
        )

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

            # ``script_breakdown`` 是 JSON dict；W5-T2 ``story_script_generate``
            # 写入时使用 ``StoryScript.model_dump()`` —— 此处直接复用为
            # ``original_script`` 注入 ``ArchetypeRewriteVars``，保持 schema 对齐。
            original_script = dict(variant.script_breakdown or {})
            if not original_script:
                raise ValueError(
                    f"StoryVariant.script_breakdown is empty: {variant_id}"
                )

            rewrite_vars = _build_rewrite_vars(
                run_args, original_script=original_script
            )

            llm = await session.run_sync(
                lambda sync_db: build_default_text_llm_sync(sync_db, thinking=False)
            )
            agent = ArchetypeVoiceRewriterAgent(llm)
            rewritten = await agent.a_rewrite_voice(vars=rewrite_vars)

            if await cancel_if_requested_async(store=store, task_id=task_id, session=session):
                log_task_event(TASK_KIND, task_id, "cancelled", stage="after_execute")
                return

            # 整段回写：与 hook/cta 不同，本任务改写**整脚本**，故直接整体替换。
            # ``mode="json"`` 保证结果是纯 JSON 兼容的基础类型，便于跨进程序列化。
            variant.script_breakdown = rewritten.model_dump(mode="json")
            variant.archetype = rewrite_vars.archetype

            payload = _build_result_payload(
                variant_id, rewrite_vars.archetype, rewritten
            )
            await store.set_result(task_id, payload)
            await store.set_progress(task_id, _SUCCEEDED_PROGRESS)
            await store.set_status(task_id, TaskStatus.succeeded)
            await session.commit()
            log_task_event(
                TASK_KIND,
                task_id,
                "succeeded",
                variant_id=variant_id,
                archetype=rewrite_vars.archetype,
            )
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


def build_archetype_rewrite_executor() -> AbstractAsyncDelegatingExecutor:
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
        runner=run_archetype_rewrite_task,
        timeout_seconds=DEFAULT_TIMEOUT_SEC,
    )


__all__ = [
    "DEFAULT_TIMEOUT_SEC",
    "TASK_KIND",
    "build_archetype_rewrite_executor",
    "run_archetype_rewrite_task",
]
