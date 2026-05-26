"""``story_script_generate`` 任务执行器（W5-T2）。

职责边界：

- 给定 ``StoryGenerationVars`` 所需的全部字段，驱动
  :class:`StoryScriptGeneratorAgent` 输出 ``StoryScript``；
- 将生成的脚本以一行 :class:`StoryVariant` 持久化（``status=ready``、
  ``compliance_score=0``、``is_champion=False``）；
- 返回包含 ``variant_id`` 与脚本结构化结果的 dict 供 worker store 写入。

不在本任务范围内（属于其他 task_kind）：

- 合规评分（W5-T3 单独的 ``story_compliance_check`` 任务）；
- API 层鉴权 / 收参（W6 端点）；
- 修改 :class:`StoryScriptGeneratorAgent`（W4-T2 拥有）或
  :class:`StoryVariant` 模型定义（W2-T2 拥有）；
- ``task_executor`` 抽象基类的修改。

执行入口 :func:`run_story_script_generate_task` 与 ``image_generation`` /
``shot_frame_prompt`` 等已有 worker 风格一致：``async def runner(task_id,
run_args) -> dict``，由
:class:`AbstractAsyncDelegatingExecutor` 桥接到 Celery 同步循环。
但本 runner 也可由测试直接 ``await``，便于以 in-memory SQLite 完整断言
持久化效果。
"""

from __future__ import annotations

import inspect
import json
import logging
import uuid
from typing import Any, Callable

from langchain_core.language_models.chat_models import BaseChatModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.chains.agents.commerce.story_script_generator_agent import StoryScriptGeneratorAgent
from app.core.contracts.story import StoryGenerationVars, StoryScript
from app.core.db import async_session_maker
from app.core.task_manager import SqlAlchemyTaskStore
from app.core.task_manager.types import TaskStatus
from app.models.story_formula import StoryVariant
from app.models.types import StoryVariantStatus
from app.services.llm.runtime import build_default_text_llm_sync
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_logging import log_task_event


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 注册元信息
# ---------------------------------------------------------------------------

#: 任务种类标识；与 ``task_executor_registry.register`` 的 key 必须一致。
TASK_KIND = "story_script_generate"

#: 默认任务超时（秒）。10 分钟覆盖单次 LLM 调用 + 持久化的合理上限，
#: 与 plan W5 「文本类合成 task_kind 默认 600s」一致。
DEFAULT_TIMEOUT_SEC: float = 600.0


#: ``StoryGenerationVars`` 所有必填字段。逐项校验避免 Pydantic 在缺失
#: dict 字段时给出含糊报错，且让 worker 早期失败而不是在 LLM 调用之后。
_REQUIRED_VARS_FIELDS: tuple[str, ...] = (
    "formula",
    "product",
    "audience",
    "archetype",
    "tone_grid",
    "target_duration_sec",
    "platform",
)


# ---------------------------------------------------------------------------
# 内部协助函数
# ---------------------------------------------------------------------------


def _require_str(run_args: dict[str, Any], key: str) -> str:
    """从 ``run_args`` 提取必需的字符串字段。

    存在原因：
        ``project_id`` / ``chapter_id`` / ``formula_id`` 这三个外键字段
        缺失时应当立即失败，避免向 :class:`StoryGenerationVars` 喂半空
        数据后再被下游约束打回，错误定位更清晰。

    参数:
        run_args: worker 入参 dict。
        key: 必需键名。

    返回:
        非空字符串值。

    异常:
        ``ValueError``: 当字段缺失或为空字符串。
    """
    value = run_args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"story_script_generate: missing or empty '{key}' in run_args")
    return value


def _build_generation_vars(run_args: dict[str, Any]) -> StoryGenerationVars:
    """从 ``run_args`` 抽取并构造 :class:`StoryGenerationVars`。

    存在原因：
        把 ``run_args -> Pydantic`` 的转换集中在一个函数里，方便单元测试
        独立断言「字段缺失 -> 明确错误」与「合法字段 -> 真实
        ``StoryGenerationVars`` 实例」两条路径。
    """
    missing = [field for field in _REQUIRED_VARS_FIELDS if field not in run_args]
    if missing:
        raise ValueError(
            "story_script_generate: missing StoryGenerationVars fields "
            f"in run_args: {sorted(missing)}"
        )
    return StoryGenerationVars(
        formula=run_args["formula"],
        product=run_args["product"],
        audience=run_args["audience"],
        archetype=run_args["archetype"],
        tone_grid=run_args["tone_grid"],
        target_duration_sec=run_args["target_duration_sec"],
        platform=run_args["platform"],
    )


def _new_variant_id() -> str:
    """生成 ``StoryVariant.id``，保持与项目其它表（``shots``、``files``）
    一致使用 ``uuid4().hex``。

    使用 ``hex`` 而非默认 36 字符串，让 ID 与 ``String(64)`` 列上现有
    `shot_id`、`file_id` 风格一致（无 dash），便于在日志中肉眼检索。
    """
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Agent 工厂（可注入，便于测试 mock）
# ---------------------------------------------------------------------------


#: ``AgentFactory`` 接收一个 ``BaseChatModel`` 并返回一个具备
#: ``a_generate_script`` 方法的对象；返回类型用 :class:`Any` 是为了让
#: 测试可以直接传入轻量 mock 而无需继承 :class:`StoryScriptGeneratorAgent`。
AgentFactory = Callable[[BaseChatModel], Any]


def _default_agent_factory(model: BaseChatModel) -> StoryScriptGeneratorAgent:
    """默认工厂：构造真实 :class:`StoryScriptGeneratorAgent`。

    单独抽出工厂的目的是允许测试通过 ``agent_factory=`` 注入 mock，
    在不打 LLM 的前提下覆盖持久化逻辑。
    """
    return StoryScriptGeneratorAgent(model)


# ---------------------------------------------------------------------------
# 主入口：异步 runner
# ---------------------------------------------------------------------------


async def run_story_script_generate_task(
    task_id: str,  # noqa: ARG001  # 由 AbstractAsyncDelegatingExecutor 注入，本 runner 仅返回 dict 由桥接层写入 store
    run_args: dict[str, Any],
    *,
    session_factory: Callable[[], AsyncSession] | None = None,
    agent_factory: AgentFactory | None = None,
    llm_factory: Callable[[Any], BaseChatModel] | None = None,
) -> dict[str, Any]:
    """生成剧情脚本并持久化为 :class:`StoryVariant` 行。

    流程：
        1. 校验三个必需字符串字段（``project_id`` / ``chapter_id`` /
           ``formula_id``）；
        2. 从 ``run_args`` 构造 :class:`StoryGenerationVars`，依赖 Pydantic
           的 ``ge=15, le=180`` 等约束做范围校验；
        3. 通过 ``llm_factory`` 在同步会话里取得默认文本 LLM；
        4. 通过 ``agent_factory`` 构造 agent 并 ``a_generate_script``；
        5. 在同一 :class:`AsyncSession` 中写入 :class:`StoryVariant`，
           ``status=ready``、``compliance_score=0``；
        6. 返回 ``{"variant_id": ..., "script": <StoryScript.model_dump()>}``
           供 worker store 写入 ``result``。

    参数:
        task_id: 由 worker 桥接层注入，本函数不直接消费。
        run_args: 任务入参，必须包含 ``project_id`` / ``chapter_id`` /
            ``formula_id`` 与全部 :class:`StoryGenerationVars` 字段。
        session_factory: 可选；返回 :class:`AsyncSession` 的工厂，便于测试
            注入 in-memory SQLite。默认走 :func:`async_session_maker`。
        agent_factory: 可选；构造 agent 的工厂，默认 :func:`_default_agent_factory`。
        llm_factory: 可选；接收同步 ``Session`` 返回 ``BaseChatModel``，
            默认 :func:`build_default_text_llm_sync` 关闭 thinking。

    返回:
        ``{"variant_id": str, "script": dict}``：``variant_id`` 用于上层
        关联，``script`` 为 :class:`StoryScript` 的 ``model_dump()`` 结果。

    异常:
        ``ValueError``: 必填字段缺失或语义违规（含 agent 抛出的时长漂移）。
        ``pydantic.ValidationError``: ``StoryGenerationVars`` 字段越界。
    """
    # 1) 必填字段。
    project_id = _require_str(run_args, "project_id")
    chapter_id = _require_str(run_args, "chapter_id")
    formula_id = _require_str(run_args, "formula_id")
    generated_by_task_id = run_args.get("generated_by_task_id")
    if generated_by_task_id is not None and not isinstance(generated_by_task_id, str):
        raise ValueError(
            "story_script_generate: 'generated_by_task_id' must be str | None"
        )

    # 2) StoryGenerationVars 校验：让 Pydantic 抛 ValidationError 上去。
    generation_vars = _build_generation_vars(run_args)

    # 3) 选择 session / llm / agent 工厂（默认值在生产路径才被使用）。
    factory = session_factory if session_factory is not None else async_session_maker
    chosen_agent_factory = agent_factory or _default_agent_factory
    chosen_llm_factory = llm_factory or (
        lambda sync_db: build_default_text_llm_sync(sync_db, thinking=False)
    )

    archetype: str | None = generation_vars.archetype or None

    async with factory() as session:
        try:
            store = SqlAlchemyTaskStore(session)
            await store.set_status(task_id, TaskStatus.running)
            await store.set_progress(task_id, 5)
            await session.commit()
            log_task_event(TASK_KIND, task_id, "running")

            llm = await session.run_sync(chosen_llm_factory)
            agent = chosen_agent_factory(llm)

            script_result = await _invoke_agent(agent, generation_vars)

            variant_id = _new_variant_id()
            script_dump = script_result.model_dump()
            variant = StoryVariant(
                id=variant_id,
                project_id=project_id,
                chapter_id=chapter_id,
                formula_id=formula_id,
                hook_pattern_id=run_args.get("hook_pattern_id"),
                cta_pattern_id=run_args.get("cta_pattern_id"),
                archetype=archetype,
                script_full_text=json.dumps(script_dump, ensure_ascii=False),
                script_breakdown=script_dump,
                status=StoryVariantStatus.ready.value,
                is_champion=False,
                compliance_score=0,
                generated_by_task_id=task_id,
            )
            session.add(variant)

            result_payload = {"variant_id": variant_id, "script": script_dump}
            await store.set_result(task_id, result_payload)
            await store.set_progress(task_id, 100)
            await store.set_status(task_id, TaskStatus.succeeded)
            await session.commit()
            await session.refresh(variant)

            logger.info(
                "story_script_generate: persisted variant %s for project=%s chapter=%s formula=%s",
                variant_id,
                project_id,
                chapter_id,
                formula_id,
            )
            log_task_event(TASK_KIND, task_id, "succeeded", variant_id=variant_id)

            return result_payload
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            async with async_session_maker() as failure_session:
                fail_store = SqlAlchemyTaskStore(failure_session)
                await fail_store.set_error(task_id, str(exc))
                await fail_store.set_status(task_id, TaskStatus.failed)
                await failure_session.commit()
            log_task_event(TASK_KIND, task_id, "failed", error=str(exc))
            raise


async def _invoke_agent(
    agent: Any,
    generation_vars: StoryGenerationVars,
) -> StoryScript:
    """单独抽出 await 调用，便于 mock 同步/异步两种实现。

    存在原因：
        测试中常用同步函数返回 ``StoryScript`` 直接 mock；这里把
        ``await`` 集中到一行，方便诊断 agent 异常时的栈帧。同时容忍
        测试 stub 直接返回 ``StoryScript`` 而非协程的形式。
    """
    result = agent.a_generate_script(vars=generation_vars)
    if inspect.isawaitable(result):
        return await result
    if isinstance(result, StoryScript):
        return result
    raise TypeError(
        f"agent.a_generate_script returned unexpected type: {type(result)!r}"
    )


# ---------------------------------------------------------------------------
# Executor 实例（向 task_executor_registry 注册时使用）
# ---------------------------------------------------------------------------


def build_story_script_generate_executor() -> AbstractAsyncDelegatingExecutor:
    """构造与 ``task_executor_registry`` 兼容的执行器实例。

    存在原因：
        把构造逻辑集中到工厂函数，便于
        ``task_registry.py`` 一行 ``register(...)`` 完成接入；同时让单测
        能直接断言 ``timeout_seconds`` 与 ``task_kind`` 默认值。

    实现细节：
        :class:`AbstractAsyncDelegatingExecutor` 期望 runner 返回
        ``Awaitable[None]``，而 :func:`run_story_script_generate_task`
        返回 ``dict`` 供测试断言；这里通过薄 adapter ``_bridge_runner``
        丢弃返回值，让类型契约对齐，并把生成结果通过 worker store 在
        生产环境中落到 ``GenerationTask.result`` 列。
    """

    async def _bridge_runner(task_id: str, run_args: dict[str, Any]) -> None:
        """适配返回 ``None`` 的 worker bridge 协议。

        生产环境调用方拿不到 dict 返回值；落库的 ``StoryVariant`` 才是
        真正的「结果」，下游通过 ``project_id + chapter_id`` 反查即可。
        """
        await run_story_script_generate_task(task_id, run_args)

    return AbstractAsyncDelegatingExecutor(
        task_kind=TASK_KIND,
        runner=_bridge_runner,
        timeout_seconds=DEFAULT_TIMEOUT_SEC,
    )


__all__ = [
    "TASK_KIND",
    "DEFAULT_TIMEOUT_SEC",
    "build_story_script_generate_executor",
    "run_story_script_generate_task",
]
