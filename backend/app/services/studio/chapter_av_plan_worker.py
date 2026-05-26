"""章节级 AV plan worker (P3 W17 T17-7)。

为何存在
--------

把 :class:`ChapterAvPlanner` 包装为 ``task.execute`` 异步任务，落到 slow
队列；遍历章节内全部 ``ShotDialogLine``，按 Decision F 决策树为每行
产出一个 :class:`DurationDecision`，并把结果回写到：

- ``ShotDialogLine.start_time_ms`` / ``end_time_ms``：方便下游字幕对齐
  与时间线导出消费；
- ``ShotDialogLine.text``：仅在 ``llm_rewrite`` 分支才更新，accept /
  speed_adjust 路径保持原文；
- ``GenerationTask.result``：``{decisions, holds, warnings}`` 三段式 dict，
  供前端任务面板展示。

设计要点
--------

- 沿用 hotfix-4 canonical worker 模板（``set_status(running)`` →
  cancel check → 业务逻辑 → cancel check → ``set_result`` → cancel
  check → ``set_status(succeeded)``），共三道 cancel checkpoint，
  避免长链路任务无法及时响应取消；
- 默认超时 ``7200s``，对齐 ``chapter_timeline_export`` 的 slow 队列 SLA；
- LLM rewriter 通过 ``_default_rewriter_invoker`` 工厂函数注入，
  单测可通过 monkeypatch 替换为 fake，避免真实 LLM 调用。
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chains.agents.commerce.duration_rewriter_agent import (
    DurationRewriteVars,
    DurationRewriterAgent,
)
from app.core.db import async_session_maker
from app.core.task_manager import SqlAlchemyTaskStore
from app.core.task_manager.types import TaskStatus
from app.models.studio_shots import Shot, ShotDetail, ShotDialogLine
from app.models.types import AudioStrategy, DialogueLineMode
from app.models.voice_pack import VoicePack
from app.services.llm.runtime import build_default_text_llm_sync
from app.services.studio.chapter_av_planner import (
    ChapterAvPlanner,
    DurationDecision,
)
from app.services.worker.async_task_support import cancel_if_requested_async
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_logging import log_task_event, log_task_failure


logger = logging.getLogger(__name__)


TASK_KIND = "chapter_av_plan"
"""注册键：与 plan ``task_kind`` 表保持一致。"""

DEFAULT_TIMEOUT_SECONDS = 7200.0
"""默认超时（秒）：与 chapter_timeline_export 一致；slow 队列。"""

_RUNNING_PROGRESS = 5
"""进入 running 时的初始进度。"""

_MID_PROGRESS = 50
"""遍历完所有 ShotDialogLine 后、写回 DB 前的进度水位。"""

_SUCCEEDED_PROGRESS = 100
"""任务成功完成时的最终进度。"""


# ---------------------------------------------------------------------------
# Rewriter 工厂：把 LLM 桥接成 ``ChapterAvPlanner`` 期望的 invoker 协议
# ---------------------------------------------------------------------------


RewriterInvoker = Callable[..., Awaitable[str]]


def _default_rewriter_invoker(session: AsyncSession) -> RewriterInvoker:
    """构造默认的 rewriter invoker：用 ``DurationRewriterAgent`` 调真实 LLM。

    设计要点:
        - LLM 通过 ``session.run_sync(build_default_text_llm_sync)`` 桥接，
          与 ``product_info_extract_worker`` 等既有 worker 保持一致；
        - 把 ``DurationRewriterAgent.a_rewrite_to_target`` 包装为
          ``(db, original_text, target_chars, line_mode) -> str`` 协议，
          让 ``ChapterAvPlanner`` 不直接依赖 Agent 类。

    参数:
        session: 当前 worker 的 async session；用于 ``run_sync`` 桥接。

    返回:
        异步 invoker，``await invoker(db, original_text=..., target_chars=...,
        line_mode=...)`` 即可拿到改写后的文本。
    """

    async def _invoker(
        _db: object,
        *,
        original_text: str,
        target_chars: int,
        line_mode: DialogueLineMode,
    ) -> str:
        llm = await session.run_sync(
            lambda sync_db: build_default_text_llm_sync(sync_db, thinking=False)
        )
        agent = DurationRewriterAgent(llm)
        result = await agent.a_rewrite_to_target(
            vars=DurationRewriteVars(
                original_text=original_text,
                target_chars=target_chars,
                line_mode=line_mode,
            )
        )
        return result.rewritten_text

    return _invoker


# ---------------------------------------------------------------------------
# 数据装载辅助
# ---------------------------------------------------------------------------


async def _load_chapter_shots_with_lines(
    session: AsyncSession, *, chapter_id: str
) -> list[tuple[Shot, ShotDetail, list[ShotDialogLine]]]:
    """加载章节内所有 ``(Shot, ShotDetail, dialog_lines)`` 三元组，按 ``Shot.index`` 排序。

    返回结构便于 worker 主循环按 "镜头优先 → 行优先" 的双层遍历，同时保证只在
    内存里持有需要写回的行。三元组比 W17-Wave3 的二元组多了 ``Shot`` 自身：
    ``audio_strategy`` 字段挂在 ``Shot`` 而非 ``ShotDetail``，必须把 ``Shot``
    一并取出，让主循环按策略分流（keep_native 跳过 Decision F 决策树）。
    """

    shot_rows = (
        await session.execute(
            select(Shot).where(Shot.chapter_id == chapter_id).order_by(Shot.index)
        )
    ).scalars().all()

    out: list[tuple[Shot, ShotDetail, list[ShotDialogLine]]] = []
    for shot in shot_rows:
        detail = await session.get(ShotDetail, shot.id)
        if detail is None:
            continue
        lines = (
            await session.execute(
                select(ShotDialogLine)
                .where(ShotDialogLine.shot_detail_id == shot.id)
                .order_by(ShotDialogLine.index)
            )
        ).scalars().all()
        out.append((shot, detail, list(lines)))
    return out


async def _resolve_voice_pack(
    session: AsyncSession, *, line: ShotDialogLine
) -> VoicePack | None:
    """解析对白行使用的 ``VoicePack``。

    优先级:
        1. ``ShotDialogLine.tts_voice_id`` 显式覆盖；
        2. fallback 到任意一条系统级音色（``is_system=True``，按 sort_order）。

    没有任何可用音色时返回 ``None``，由调用方决定是否跳过该行。
    """

    if line.tts_voice_id:
        pack = await session.get(VoicePack, line.tts_voice_id)
        if pack is not None:
            return pack
    fallback = (
        await session.execute(
            select(VoicePack)
            .where(VoicePack.is_system.is_(True))
            .order_by(VoicePack.sort_order, VoicePack.id)
        )
    ).scalars().first()
    return fallback


# ---------------------------------------------------------------------------
# 决策结果回写
# ---------------------------------------------------------------------------


def _apply_decision_to_line(
    *, line: ShotDialogLine, decision: DurationDecision, start_time_ms: int
) -> None:
    """把单条决策结果写入 ``ShotDialogLine``。

    - 所有 action 都会写入 ``start_time_ms`` / ``end_time_ms``；
    - 仅 ``llm_rewrite`` 分支会覆盖 ``text``；
    - ``hold`` / ``speed_adjust`` / ``accept`` 保持原文。
    """

    line.start_time_ms = start_time_ms
    line.end_time_ms = start_time_ms + max(0, decision.estimated_ms)
    if decision.action == "llm_rewrite":
        line.text = decision.final_text


def _serialize_decision(decision: DurationDecision) -> dict[str, Any]:
    """把决策序列化成 JSON-friendly dict，便于写入 ``GenerationTask.result``。"""

    return {
        "dialog_line_id": decision.dialog_line_id,
        "action": decision.action,
        "original_text": decision.original_text,
        "final_text": decision.final_text,
        "suggested_speed": decision.suggested_speed,
        "target_duration_ms": decision.target_duration_ms,
        "estimated_ms": decision.estimated_ms,
        "rewrite_attempts": decision.rewrite_attempts,
        "warning": decision.warning,
    }


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


async def run_chapter_av_plan_task(
    task_id: str,
    run_args: dict[str, Any],
) -> None:
    """异步 runner：为指定章节产出全镜头的 AV plan。

    输入 (``run_args``):
        - ``chapter_id`` (str, required): 目标章节 ID。

    输出（写入 ``store.set_result`` 的 dict）:
        - ``chapter_id``: 章节 ID；
        - ``decisions``: 每条 ``ShotDialogLine`` 的决策序列化；
        - ``holds``: 需要人工介入的 ``dialog_line_id`` 列表；
        - ``warnings``: ``[{line_id, warning}, ...]`` 列表，便于前端展示。

    异常处理:
        与 ``product_info_extract_worker`` 保持一致：try 中 rollback、
        独立会话写 failed、再向上抛由 ``AbstractAsyncDelegatingExecutor``
        转换为 Celery 失败状态。
    """

    chapter_id = str(run_args.get("chapter_id") or "").strip()
    if not chapter_id:
        raise ValueError("chapter_av_plan requires non-empty chapter_id in run_args")

    async with async_session_maker() as session:
        try:
            store = SqlAlchemyTaskStore(session)
            await store.set_status(task_id, TaskStatus.running)
            await store.set_progress(task_id, _RUNNING_PROGRESS)
            await session.commit()
            log_task_event(TASK_KIND, task_id, "running", chapter_id=chapter_id)

            # Cancel checkpoint #1：进入业务逻辑前。
            if await cancel_if_requested_async(
                store=store, task_id=task_id, session=session
            ):
                log_task_event(TASK_KIND, task_id, "cancelled", stage="before_iterate")
                return

            invoker = _default_rewriter_invoker(session)
            planner = ChapterAvPlanner(rewriter_invoker=invoker)

            shots_and_lines = await _load_chapter_shots_with_lines(
                session, chapter_id=chapter_id
            )
            decisions: list[DurationDecision] = []
            holds: list[int] = []
            warnings: list[dict[str, Any]] = []

            for shot, detail, lines in shots_and_lines:
                shot_duration_ms = max(0, int(detail.duration or 0)) * 1000
                # SQLAlchemy String 列回读为 raw str，需 coerce 回 AudioStrategy
                # 才能让下游 == 比较与 Literal 匹配稳定。
                raw_strategy = shot.audio_strategy or AudioStrategy.silent_with_tts
                audio_strategy = (
                    raw_strategy
                    if isinstance(raw_strategy, AudioStrategy)
                    else AudioStrategy(raw_strategy)
                )
                cursor = 0
                for line in lines:
                    # keep_native：模型自带原音决定时长，planner 不做 text/speed
                    # reconcile，跳过 voice_pack 解析与 Decision F 决策树。直接
                    # inline 构造 skip_native 决策；下游 ASR 反推字幕时再校准时间戳。
                    if audio_strategy == AudioStrategy.keep_native:
                        skip_decision = DurationDecision(
                            dialog_line_id=int(line.id),
                            action="skip_native",
                            original_text=line.text,
                            final_text=line.text,
                            suggested_speed=1.0,
                            target_duration_ms=shot_duration_ms,
                            estimated_ms=shot_duration_ms,
                        )
                        decisions.append(skip_decision)
                        _apply_decision_to_line(
                            line=line, decision=skip_decision, start_time_ms=cursor
                        )
                        cursor = (line.end_time_ms or 0)
                        continue

                    voice_pack = await _resolve_voice_pack(session, line=line)
                    if voice_pack is None:
                        # 没有可用音色：标记为 hold，不进入决策树以避免误估。
                        warning = (
                            "未配置 tts_voice_id，且系统默认音色不可用，"
                            "需要人工指定后重试"
                        )
                        decisions.append(
                            DurationDecision(
                                dialog_line_id=int(line.id),
                                action="hold",
                                original_text=line.text,
                                final_text=line.text,
                                suggested_speed=1.0,
                                target_duration_ms=shot_duration_ms,
                                estimated_ms=0,
                                rewrite_attempts=0,
                                warning=warning,
                            )
                        )
                        holds.append(int(line.id))
                        warnings.append({"line_id": int(line.id), "warning": warning})
                        continue

                    decision = await planner.plan_dialog_line(
                        db=session,
                        line=line,
                        shot_duration_ms=shot_duration_ms,
                        voice_pack=voice_pack,
                        audio_strategy=audio_strategy,
                    )
                    decisions.append(decision)
                    if decision.action == "hold":
                        holds.append(decision.dialog_line_id)
                        if decision.warning:
                            warnings.append(
                                {
                                    "line_id": decision.dialog_line_id,
                                    "warning": decision.warning,
                                }
                            )
                    _apply_decision_to_line(
                        line=line, decision=decision, start_time_ms=cursor
                    )
                    cursor = (line.end_time_ms or 0)

            # Cancel checkpoint #2：决策完成、写库前。
            if await cancel_if_requested_async(
                store=store, task_id=task_id, session=session
            ):
                log_task_event(TASK_KIND, task_id, "cancelled", stage="after_iterate")
                return

            await store.set_progress(task_id, _MID_PROGRESS)
            await session.flush()

            payload: dict[str, Any] = {
                "chapter_id": chapter_id,
                "decisions": [_serialize_decision(d) for d in decisions],
                "holds": holds,
                "warnings": warnings,
            }
            await store.set_result(task_id, payload)

            # Cancel checkpoint #3：写完 result 但还未推进到 succeeded 之前。
            if await cancel_if_requested_async(
                store=store, task_id=task_id, session=session
            ):
                log_task_event(TASK_KIND, task_id, "cancelled", stage="after_persist")
                return

            await store.set_progress(task_id, _SUCCEEDED_PROGRESS)
            await store.set_status(task_id, TaskStatus.succeeded)
            await session.commit()
            log_task_event(
                TASK_KIND,
                task_id,
                "succeeded",
                chapter_id=chapter_id,
                hold_count=len(holds),
                decision_count=len(decisions),
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


# ---------------------------------------------------------------------------
# Executor 工厂
# ---------------------------------------------------------------------------


def build_chapter_av_plan_executor() -> AbstractAsyncDelegatingExecutor:
    """构造与 ``task_executor_registry`` 兼容的 chapter_av_plan 执行器实例。"""

    return AbstractAsyncDelegatingExecutor(
        task_kind=TASK_KIND,
        runner=run_chapter_av_plan_task,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
    )


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "TASK_KIND",
    "build_chapter_av_plan_executor",
    "run_chapter_av_plan_task",
]
