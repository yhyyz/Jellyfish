"""团队级 BLOCKER 升级引擎（W26-T2）。

做什么：
    在 W26-T1 dispatcher 的 fan-out 之后，对 **同一 profile / 团队** 的连续
    BLOCKER 做"滑动窗口 + 计数器"判定：

        默认：``24h`` 窗口内连续 ``3`` 次 BLOCKER → 触发额外 owner 通知。

    阈值与窗口长度从 :class:`ComplianceProfile.rules` 中读取（约定
    `{"escalation": {"threshold": N, "window_hours": H}}`），缺省回退到默认
    值。owner 邮箱来自环境变量 ``ESCALATION_OWNER_EMAIL``（无 User 表，
    不引入 RBAC）。

为什么独立模块：
    - dispatcher 已经背负 fan-out + 重试 + 失败日志，再塞升级策略会让单
      文件难以测试；
    - 升级判定本质是"读 / 写计数器 + 条件下发额外通知"，与渠道发送解
      耦，便于独立 TDD（无窗口 / 到阈值 / 二次触发去抖 / 窗口重置）。

边界：
    - 不修改 dispatcher 的 fan-out 主路径，仅在 fan-out 完成后被 dispatcher
      调用一次；
    - 不依赖 :class:`NotificationChannel` 配置，owner 通知走单一 email 路径
      （SMTP + ESCALATION_OWNER_EMAIL）；缺任一前置条件直接 no-op；
    - 不引入 RBAC / User 表；
    - 触发后清零计数器并清空 ``window_start_at``，避免连续触发"放大风暴"。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.notifications.email import (
    EmailDeliveryError,
    SmtpConfig,
    send_email,
)
from app.models.compliance import ComplianceProfile
from app.models.escalation_state import EscalationState


logger = logging.getLogger(__name__)


# 默认升级策略：与 W19b/W26-T2 周计划文档一致。
DEFAULT_THRESHOLD: int = 3
DEFAULT_WINDOW_HOURS: int = 24

# 全局兜底 escalation key（profile_id 缺省时使用）。
_GLOBAL_KEY: str = "__global__"


@dataclass(frozen=True)
class EscalationConfig:
    """单次判定使用的策略快照。"""

    threshold: int
    window_hours: int


@dataclass
class EscalationOutcome:
    """单次 ``maybe_escalate`` 的可观测结果（测试 + 监控用）。"""

    counted: bool = False
    consecutive_blockers: int = 0
    triggered: bool = False
    skipped_reason: str | None = None


# ---------------------------------------------------------------------------
# 配置解析：从 ComplianceProfile.rules 抽取 escalation 配置
# ---------------------------------------------------------------------------


def _extract_config_from_rules(rules: Any) -> EscalationConfig:
    """从 ``ComplianceProfile.rules`` 解析 escalation 策略。

    约定（任一种存在即可，按顺序优先）：

        1. ``rules`` 为 ``dict`` 且含 ``escalation`` 键：
           ``{"escalation": {"threshold": N, "window_hours": H}}``；
        2. ``rules`` 为 ``list``，且某条目为
           ``{"escalation": {"threshold": N, "window_hours": H}}``；
        3. ``rules`` 为 ``list``，且某条目自身 ``kind == "escalation"``，
           其它键扁平挂在条目上（``threshold`` / ``window_hours``）。

    任一字段缺失或类型不合法时回退到 :data:`DEFAULT_THRESHOLD` /
    :data:`DEFAULT_WINDOW_HOURS`。
    """

    threshold = DEFAULT_THRESHOLD
    window_hours = DEFAULT_WINDOW_HOURS

    candidate: dict[str, Any] | None = None

    if isinstance(rules, dict):
        cfg = rules.get("escalation")
        if isinstance(cfg, dict):
            candidate = cfg
    elif isinstance(rules, list):
        for item in rules:
            if not isinstance(item, dict):
                continue
            cfg = item.get("escalation")
            if isinstance(cfg, dict):
                candidate = cfg
                break
            if item.get("kind") == "escalation":
                candidate = item
                break

    if candidate:
        raw_threshold = candidate.get("threshold")
        raw_window = candidate.get("window_hours")
        if isinstance(raw_threshold, int) and raw_threshold > 0:
            threshold = raw_threshold
        if isinstance(raw_window, int) and raw_window > 0:
            window_hours = raw_window

    return EscalationConfig(threshold=threshold, window_hours=window_hours)


async def _load_config(
    session: AsyncSession,
    *,
    profile_id: str | None,
) -> EscalationConfig:
    """从 DB 加载 profile 的 escalation 策略；缺省走默认。"""

    if not profile_id:
        return EscalationConfig(
            threshold=DEFAULT_THRESHOLD,
            window_hours=DEFAULT_WINDOW_HOURS,
        )
    profile = await session.get(ComplianceProfile, profile_id)
    if profile is None:
        return EscalationConfig(
            threshold=DEFAULT_THRESHOLD,
            window_hours=DEFAULT_WINDOW_HOURS,
        )
    return _extract_config_from_rules(profile.rules)


# ---------------------------------------------------------------------------
# 状态读 / 写
# ---------------------------------------------------------------------------


def _state_key(*, profile_id: str | None, team_id: str | None) -> str:
    """构造稳定 PK：profile 优先，team 次之，否则全局兜底。"""

    if profile_id:
        return f"profile:{profile_id}"
    if team_id:
        return f"team:{team_id}"
    return _GLOBAL_KEY


async def _get_or_create_state(
    session: AsyncSession,
    *,
    profile_id: str | None,
    team_id: str | None,
) -> EscalationState:
    """SELECT or INSERT escalation state；不主动 commit。"""

    key = _state_key(profile_id=profile_id, team_id=team_id)
    row = (
        await session.execute(
            select(EscalationState).where(EscalationState.id == key)
        )
    ).scalar_one_or_none()
    if row is not None:
        return row

    row = EscalationState(
        id=key,
        profile_id=profile_id,
        team_id=team_id,
        consecutive_blockers=0,
        window_start_at=None,
        last_escalated_at=None,
    )
    session.add(row)
    # flush 让后续 SELECT 看到（同一事务内）；提交交给上层。
    await session.flush()
    return row


# ---------------------------------------------------------------------------
# owner 通知
# ---------------------------------------------------------------------------


def _build_escalation_body(
    *,
    profile_id: str | None,
    team_id: str | None,
    consecutive: int,
    threshold: int,
    window_hours: int,
    finding_id: int | None,
    rule_id: str,
    description: str,
    variant_id: str | None,
) -> str:
    """构造 owner 通知邮件的纯文本正文。"""

    lines = [
        "Compliance escalation: consecutive BLOCKERs",
        "",
        f"Scope         : profile={profile_id or '-'} team={team_id or '-'}",
        f"Threshold     : {consecutive} >= {threshold} within {window_hours}h",
    ]
    if finding_id is not None:
        lines.append(f"Last finding  : id={finding_id} rule={rule_id}")
    else:
        lines.append(f"Last rule     : {rule_id}")
    if variant_id:
        lines.append(f"Variant ID    : {variant_id}")
    lines.extend(["", "Latest description:", description, ""])
    return "\n".join(lines)


async def _notify_owner(
    *,
    smtp_config: SmtpConfig,
    smtp_sender: str,
    owner_email: str,
    subject: str,
    body: str,
    email_sender: Callable[..., Awaitable[None]],
) -> bool:
    """发送 owner 通知；失败仅记日志，不向上抛。"""

    try:
        await email_sender(
            config=smtp_config,
            sender=smtp_sender,
            recipients=[owner_email],
            subject=subject,
            body=body,
        )
        return True
    except EmailDeliveryError as exc:
        logger.warning("escalation owner email failed: %s", exc)
    except Exception:  # noqa: BLE001
        logger.exception("escalation owner email raised unexpected error")
    return False


# ---------------------------------------------------------------------------
# 公开入口：maybe_escalate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EscalationInput:
    """``maybe_escalate`` 入参快照。

    与 :class:`BlockerFindingPayload` 解耦，避免 escalation_engine 与
    dispatcher 形成强耦合；dispatcher 在调用时按需投影即可。
    """

    finding_id: int | None
    rule_id: str
    description: str
    profile_id: str | None = None
    team_id: str | None = None
    variant_id: str | None = None


async def maybe_escalate(
    session: AsyncSession,
    payload: EscalationInput,
    *,
    smtp_config: SmtpConfig | None,
    smtp_sender: str | None,
    owner_email: str | None,
    now: datetime | None = None,
    email_sender: Callable[..., Awaitable[None]] = send_email,
) -> EscalationOutcome:
    """在已有 BLOCKER 之上做"窗口 + 计数器"升级判定。

    流程：
        1. 加载策略：``threshold`` / ``window_hours``（来自 profile.rules
           或默认）；
        2. SELECT-or-INSERT 当前 scope 的 :class:`EscalationState`；
        3. 判定窗口：若 ``window_start_at`` 为空 / 已超时，则用当前时间
           重置为新窗口起点，计数器清零；
        4. 计数器 +1（首次进入新窗口时计数为 1）；
        5. 若计数 ``>= threshold``：
            - 调 owner 通知（owner_email / smtp_config / smtp_sender 任一
              缺失则跳过通知，但仍标记 ``triggered=True`` 以便监控）；
            - 重置计数器为 0、清空 ``window_start_at``；
            - 记录 ``last_escalated_at = now``。

    Args:
        session: 调用方提供的 async session（dispatcher 复用同一 session）。
        payload: 升级判定快照。
        smtp_config / smtp_sender / owner_email: owner 通知三件套；任一缺
            失时升级判定仍正常计数，只是不发邮件。
        now: 测试可注入"当前时间"；缺省取 ``datetime.now(timezone.utc)``。
        email_sender: 测试 hook。

    Returns:
        :class:`EscalationOutcome`：是否计数、是否触发、当前计数值。
    """

    outcome = EscalationOutcome()

    if payload.profile_id is None and payload.team_id is None:
        # 没有归属维度时不做升级（保留全局桶反而易误触发）。
        outcome.skipped_reason = "no scope"
        return outcome

    current_time = now or datetime.now(timezone.utc)
    config = await _load_config(session, profile_id=payload.profile_id)

    state = await _get_or_create_state(
        session,
        profile_id=payload.profile_id,
        team_id=payload.team_id,
    )

    window = timedelta(hours=config.window_hours)
    window_expired = (
        state.window_start_at is None
        or _ensure_aware(state.window_start_at) + window <= current_time
    )

    if window_expired:
        state.window_start_at = current_time
        state.consecutive_blockers = 1
    else:
        state.consecutive_blockers = (state.consecutive_blockers or 0) + 1

    outcome.counted = True
    outcome.consecutive_blockers = state.consecutive_blockers

    if state.consecutive_blockers >= config.threshold:
        outcome.triggered = True
        if smtp_config is not None and smtp_sender and owner_email:
            body = _build_escalation_body(
                profile_id=payload.profile_id,
                team_id=payload.team_id,
                consecutive=state.consecutive_blockers,
                threshold=config.threshold,
                window_hours=config.window_hours,
                finding_id=payload.finding_id,
                rule_id=payload.rule_id,
                description=payload.description,
                variant_id=payload.variant_id,
            )
            subject = (
                f"[Compliance Escalation] {state.consecutive_blockers} "
                f"BLOCKERs within {config.window_hours}h"
            )
            await _notify_owner(
                smtp_config=smtp_config,
                smtp_sender=smtp_sender,
                owner_email=owner_email,
                subject=subject,
                body=body,
                email_sender=email_sender,
            )
        else:
            logger.info(
                "escalation triggered but owner notify skipped (no smtp/owner)",
                extra={
                    "profile_id": payload.profile_id,
                    "team_id": payload.team_id,
                    "consecutive": state.consecutive_blockers,
                },
            )
        # 触发后重置：避免后续每条 BLOCKER 都连续触发。
        state.consecutive_blockers = 0
        state.window_start_at = None
        state.last_escalated_at = current_time

    await session.flush()
    return outcome


def _ensure_aware(value: datetime) -> datetime:
    """把 naive datetime 视为 UTC，便于跨 SQLite/MySQL 比较。

    SQLite 存储 ``DateTime(timezone=True)`` 时会丢 tz info，重新加载后
    成为 naive；这里统一补回 UTC 语义，避免与 ``current_time``（aware）
    做比较时报 ``TypeError``。
    """

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


__all__ = [
    "DEFAULT_THRESHOLD",
    "DEFAULT_WINDOW_HOURS",
    "EscalationConfig",
    "EscalationInput",
    "EscalationOutcome",
    "maybe_escalate",
]
