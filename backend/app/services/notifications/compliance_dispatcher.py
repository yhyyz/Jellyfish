"""合规 BLOCKER 告警 fan-out dispatcher（W26-T1）。

做什么：
    给定一条已落库的合规 finding（severity=blocker）+ 调用方上下文
    （variant_id 等），dispatcher 负责：

    1. 从 ``notification_channels`` 取出"匹配该 profile 且 enabled"的
       全部 Slack/email 渠道（profile_id 匹配 + 全局兜底）；
    2. 用 :func:`asyncio.gather` 并发投递（每个渠道一个 task）；
    3. 单渠道内做 3 次指数退避重试（1s / 2s / 4s）；
    4. 重试用尽仍失败的渠道，写入 ``notification_deliveries`` 失败日志；
    5. 整体不会向上抛异常（fan-out 不应阻塞主业务）。

为什么 commit 之后再 fire：
    遵循 W19b chain dispatch 契约 —— "数据已落地"是一切下游链路的先
    决条件，避免出现"通知发了但事务回滚"的鬼故事。worker 在
    ``await session.commit()`` 之后再 schedule dispatcher。

为什么用 BackgroundTasks（在 API 层）/ create_task（在 worker 层）：
    告警 fan-out 是"best-effort"，不能阻塞 API response 或 worker
    主流程。FastAPI ``BackgroundTasks.add_task`` 在 response 已发出后
    才执行，worker 走 ``asyncio.create_task`` 即可。

边界：
    - 不实装 escalation rules（T26-2 owns）；
    - 不修改 :class:`ComplianceFinding`；
    - 重试与并发都在 dispatcher 内部解决，integration 层不关心。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_maker
from app.integrations.notifications.email import (
    EmailDeliveryError,
    SmtpConfig,
    build_compliance_email_body,
    send_email,
)
from app.integrations.notifications.slack import (
    SlackDeliveryError,
    build_compliance_blocks,
    send_slack_webhook,
)
from app.models.notification_channel import NotificationChannel
from app.services.notifications.delivery_log import record_failed_delivery


logger = logging.getLogger(__name__)


# 重试配置：3 次尝试 + 指数退避（首次失败后 1s，再失败后 2s，再失败后 4s）。
# 与端到端 5s SLA 的关系：单次 HTTP 超时 3s，理想路径首次成功；首次失败时
# 重试不再卡 SLA（已超 5s 也接受，只为可达性）。
_MAX_ATTEMPTS: int = 3
_BACKOFF_SCHEDULE_SEC: tuple[float, ...] = (1.0, 2.0, 4.0)


@dataclass(frozen=True)
class BlockerFindingPayload:
    """dispatcher 入参：BLOCKER finding 的关键信息快照。

    设计上**不**直接传 ORM 实体，因为 dispatcher 在 BackgroundTasks /
    create_task 异步路径上跑，原始 session 此时可能已关闭，跨 session
    懒加载实体属性会出错。这里走"提前抓取关键字段"的明文 payload。
    """

    finding_id: int | None
    severity: str
    rule_id: str
    rule_kind: str
    description: str
    variant_id: str | None = None
    profile_id: str | None = None
    location: str | None = None
    suggested_fix: str | None = None
    title: str = "Compliance BLOCKER"


@dataclass
class DispatcherResult:
    """fan-out 完成后的统计结果（测试 + 指标暴露用）。"""

    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    failed_channels: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 渠道加载
# ---------------------------------------------------------------------------


async def _load_active_channels(
    session: AsyncSession,
    *,
    profile_id: str | None,
) -> list[NotificationChannel]:
    """取出对该 profile 生效的全部启用渠道。

    匹配规则：
        - ``profile_id == 入参 profile_id`` 的渠道（精确绑定）；
        - 或 ``profile_id IS NULL`` 的渠道（全局兜底）。
    """

    stmt = select(NotificationChannel).where(NotificationChannel.enabled.is_(True))
    if profile_id:
        stmt = stmt.where(
            (NotificationChannel.profile_id == profile_id)
            | (NotificationChannel.profile_id.is_(None))
        )
    else:
        stmt = stmt.where(NotificationChannel.profile_id.is_(None))
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


# ---------------------------------------------------------------------------
# 单渠道发送 + 重试封装
# ---------------------------------------------------------------------------


async def _send_with_retry(
    *,
    sender: Callable[[], Awaitable[None]],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> tuple[int, Exception | None]:
    """对一次性 ``sender`` 协程做 3 次指数退避重试。

    Args:
        sender: 单次发送的无参协程（partial / lambda）。
        sleep: 可注入的 sleep 实现，便于测试用 zero-sleep。

    Returns:
        ``(attempts_done, last_error_or_None)``。
        全部成功时 ``last_error`` 为 ``None``；3 次都失败时 ``attempts_done``
        固定为 ``_MAX_ATTEMPTS``。
    """

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            await sender()
            return attempt, None
        except (SlackDeliveryError, EmailDeliveryError, asyncio.TimeoutError) as exc:
            last_exc = exc
            if attempt >= _MAX_ATTEMPTS:
                break
            backoff = _BACKOFF_SCHEDULE_SEC[attempt - 1]
            logger.info(
                "notification attempt failed; will retry",
                extra={"attempt": attempt, "backoff_sec": backoff, "error": str(exc)},
            )
            await sleep(backoff)
        except Exception as exc:  # noqa: BLE001
            # 非预期异常：记录并不再重试，避免无限堆叠。
            last_exc = exc
            logger.exception("notification attempt raised unexpected error")
            break
    return _MAX_ATTEMPTS, last_exc


# ---------------------------------------------------------------------------
# 单渠道路由：根据 kind 调对应 integration
# ---------------------------------------------------------------------------


async def _deliver_channel(
    channel: NotificationChannel,
    payload: BlockerFindingPayload,
    *,
    smtp_config: SmtpConfig | None,
    smtp_sender: str | None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    slack_sender: Callable[..., Awaitable[None]] = send_slack_webhook,
    email_sender: Callable[..., Awaitable[None]] = send_email,
) -> tuple[bool, int, str | None]:
    """投递到单个渠道（含 3 次重试）。

    Returns:
        ``(succeeded, attempts, error_str_or_None)``。
    """

    if channel.kind == "slack":
        blocks = build_compliance_blocks(
            finding_id=payload.finding_id,
            severity=payload.severity,
            rule_id=payload.rule_id,
            rule_kind=payload.rule_kind,
            description=payload.description,
            variant_id=payload.variant_id,
            location=payload.location,
            suggested_fix=payload.suggested_fix,
            title=payload.title,
        )
        text_fallback = f"[BLOCKER] {payload.rule_id}: {payload.description}"

        async def _slack() -> None:
            await slack_sender(
                channel.target,
                text=text_fallback,
                blocks=blocks,
            )

        attempts, exc = await _send_with_retry(sender=_slack, sleep=sleep)
        return (exc is None), attempts, (None if exc is None else str(exc))

    if channel.kind == "email":
        if smtp_config is None or not smtp_sender:
            return False, 0, "smtp not configured"
        body = build_compliance_email_body(
            finding_id=payload.finding_id,
            severity=payload.severity,
            rule_id=payload.rule_id,
            rule_kind=payload.rule_kind,
            description=payload.description,
            variant_id=payload.variant_id,
            location=payload.location,
            suggested_fix=payload.suggested_fix,
        )
        subject = f"[Compliance BLOCKER] {payload.rule_id}"
        recipients = [r.strip() for r in channel.target.split(",") if r.strip()]

        async def _email() -> None:
            await email_sender(
                config=smtp_config,
                sender=smtp_sender,
                recipients=recipients,
                subject=subject,
                body=body,
            )

        attempts, exc = await _send_with_retry(sender=_email, sleep=sleep)
        return (exc is None), attempts, (None if exc is None else str(exc))

    # 未知 kind 直接视为失败，但不抛
    return False, 0, f"unsupported channel kind: {channel.kind}"


# ---------------------------------------------------------------------------
# 公开入口：dispatch
# ---------------------------------------------------------------------------


async def dispatch_blocker_finding(
    payload: BlockerFindingPayload,
    *,
    session: AsyncSession | None = None,
    smtp_config: SmtpConfig | None = None,
    smtp_sender: str | None = None,
    channels_override: Sequence[NotificationChannel] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    slack_sender: Callable[..., Awaitable[None]] = send_slack_webhook,
    email_sender: Callable[..., Awaitable[None]] = send_email,
) -> DispatcherResult:
    """对单条 BLOCKER finding 触发 fan-out。

    Args:
        payload: finding 关键信息快照。
        session: 可选的外部 session；为 ``None`` 时函数内部用
            ``async_session_maker()`` 自管事务（适合 BackgroundTasks /
            ``asyncio.create_task`` 调用方）。
        smtp_config / smtp_sender: SMTP 配置；缺省时 email 渠道直接判失败。
        channels_override: 测试用，绕过 DB 直接传渠道列表。
        sleep / slack_sender / email_sender: 测试 hook。

    Returns:
        :class:`DispatcherResult` 统计；本函数永不抛异常。
    """

    result = DispatcherResult()
    own_session = session is None

    async def _run(s: AsyncSession) -> None:
        if channels_override is not None:
            channels = list(channels_override)
        else:
            channels = await _load_active_channels(s, profile_id=payload.profile_id)
        if not channels:
            logger.info(
                "no active notification channels; skip dispatch",
                extra={"profile_id": payload.profile_id},
            )
            return

        async def _one(channel: NotificationChannel) -> tuple[NotificationChannel, bool, int, str | None]:
            ok, attempts, err = await _deliver_channel(
                channel,
                payload,
                smtp_config=smtp_config,
                smtp_sender=smtp_sender,
                sleep=sleep,
                slack_sender=slack_sender,
                email_sender=email_sender,
            )
            return channel, ok, attempts, err

        outcomes = await asyncio.gather(
            *(_one(c) for c in channels),
            return_exceptions=False,
        )

        for channel, ok, attempts, err in outcomes:
            result.attempted += 1
            if ok:
                result.succeeded += 1
                continue
            result.failed += 1
            result.failed_channels.append(channel.id)
            try:
                await record_failed_delivery(
                    s,
                    channel_id=channel.id,
                    finding_id=payload.finding_id,
                    kind=channel.kind,
                    target=channel.target,
                    attempts=attempts,
                    error=err or "unknown",
                )
            except Exception:  # noqa: BLE001
                # 写日志失败不应放大主路径错误；仅 log。
                logger.exception("failed to record notification delivery row")

    try:
        if own_session:
            async with async_session_maker() as s:
                await _run(s)
                await s.commit()
        else:
            await _run(session)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        logger.exception(
            "compliance dispatcher unexpected failure",
            extra={"finding_id": payload.finding_id},
        )

    logger.info(
        "compliance dispatcher fan-out complete",
        extra={
            "finding_id": payload.finding_id,
            "attempted": result.attempted,
            "succeeded": result.succeeded,
            "failed": result.failed,
        },
    )
    return result


async def dispatch_blocker_findings(
    payloads: Iterable[BlockerFindingPayload],
    **kwargs,
) -> list[DispatcherResult]:
    """批量入口：对 N 条 BLOCKER finding 并发 fan-out。

    用 ``asyncio.gather`` 让 N 条 finding 之间也并行（单条 finding 内部
    渠道也并行）。
    """

    pl = list(payloads)
    if not pl:
        return []
    return list(
        await asyncio.gather(
            *(dispatch_blocker_finding(p, **kwargs) for p in pl),
            return_exceptions=False,
        )
    )


__all__ = [
    "BlockerFindingPayload",
    "DispatcherResult",
    "dispatch_blocker_finding",
    "dispatch_blocker_findings",
]
