"""通知投递日志写入助手（W26-T1）。

为什么独立成模块：
    dispatcher 只关心"投递一次失败要不要写库"这一件事；具体写哪张表、
    用哪个 session、字段长度截断逻辑等本来就该被封装。把这层逻辑抽到
    单独模块后：

    - dispatcher 测试可以纯 mock 这一函数；
    - 后续如果要把"成功也记一行"或"按渠道滚动 7 天清理"，不会污染
      dispatcher 主流程。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_channel import NotificationDelivery


logger = logging.getLogger(__name__)


# 数据库列长度上限，超过后裁剪以防止 SMTP 异常 stack trace 把整个
# error 列撑爆（SQLite 不强制 String 长度，但 MySQL 强制）。
_ERROR_COLUMN_HARD_LIMIT: int = 8000


async def record_failed_delivery(
    session: AsyncSession,
    *,
    channel_id: str,
    finding_id: int | None,
    kind: str,
    target: str,
    attempts: int,
    error: str,
) -> None:
    """把一次"重试用尽仍失败"的投递写入 ``notification_deliveries``。

    Args:
        session: 写入用的异步 session；调用方负责 commit / rollback。
        channel_id: 对应 :class:`NotificationChannel.id`。
        finding_id: 触发的 :class:`ComplianceFinding.id`，可为 ``None``。
        kind: ``slack`` 或 ``email``，作为快照写入。
        target: 投递目标快照（webhook URL 或 email），便于事后审计。
        attempts: 实际尝试次数（含首次）。
        error: 最后一次失败的错误描述（异常 ``str()`` 即可）。
    """

    truncated_error = error if len(error) <= _ERROR_COLUMN_HARD_LIMIT else (
        error[: _ERROR_COLUMN_HARD_LIMIT - 3] + "..."
    )
    truncated_target = target[:512] if len(target) > 512 else target

    session.add(
        NotificationDelivery(
            channel_id=channel_id,
            finding_id=finding_id,
            kind=kind,
            target=truncated_target,
            attempts=attempts,
            error=truncated_error,
            failed_at=datetime.now(timezone.utc),
        )
    )
    logger.warning(
        "notification delivery failed; recorded to notification_deliveries",
        extra={
            "channel_id": channel_id,
            "finding_id": finding_id,
            "kind": kind,
            "attempts": attempts,
        },
    )


__all__ = ["record_failed_delivery"]
