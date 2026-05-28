"""通知渠道与投递日志 ORM 模型（W26-T1）。

为什么存在：
    P4 W26-T1 引入"合规 BLOCKER finding 写入后异步 fan-out 到 Slack +
    email"的告警子系统。系统需要两类持久化：

    1. :class:`NotificationChannel` —— 配置层：记录"哪个 profile 配置
       了哪几个告警渠道"（Slack webhook URL / email 收件人）；可启用/
       禁用，可关联到具体的 :class:`ComplianceProfile`，也可作为全局
       fallback 渠道（``profile_id=NULL``）。
    2. :class:`NotificationDelivery` —— 投递日志：每次 dispatcher 试图
       投递告警的结果，**只在失败时**入表（成功路径只记日志，避免
       表无限增长）；记录 ``channel_id`` / ``finding_id`` / 重试次数 /
       最后的错误描述，方便人工排查"为什么 Slack 没收到"这类问题。

边界：
    - 本模块**不**定义任何 escalation rule / 升级策略（T26-2 owns）；
    - 本模块只暴露 ORM 模型，不包含发送逻辑（dispatcher / integrations
      在 :mod:`app.services.notifications` / :mod:`app.integrations.notifications`）；
    - ``NotificationDelivery`` 不通过 FK 强约束 finding：finding 是
      自增 int，且 dispatcher 走 BackgroundTasks 异步路径，写日志时
      事务可能已提交，使用纯字段引用更稳；保留 index 便于按 finding
      回查。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin


class NotificationChannel(Base, TimestampMixin):
    """合规告警通知渠道。

    主要字段：
        id: 稳定字符串 ID（如 ``slack_default``、``email_legal_team``）。
        profile_id: 可选关联到某个 :class:`ComplianceProfile`；为 ``None``
            表示全局兜底渠道（任意 profile 触发的 BLOCKER 都会通知）。
        kind: ``slack`` 或 ``email``，决定 dispatcher 走哪个 integration。
        target: Slack 路径下是 webhook URL；email 路径下是收件人地址。
        secret_ref: 可选，引用外部 secret manager 中的密钥别名（不直接
            存密钥本体）；当前 P4 暂不消费此字段，只作为前向兼容。
        enabled: 软关停开关，dispatcher 只 fan-out ``enabled=True`` 渠道。
        description: 中文说明，前端展示与运维记忆用。
    """

    __tablename__ = "notification_channels"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        comment="稳定字符串 ID",
    )
    profile_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("compliance_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="可选关联到某个合规 profile；NULL=全局兜底渠道",
    )
    kind: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        index=True,
        comment="渠道类型：slack / email",
    )
    target: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        comment="Slack webhook URL 或 email 收件人地址",
    )
    secret_ref: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        default=None,
        comment="可选 secret manager 引用别名（当前未消费，前向兼容）",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
        comment="是否启用",
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
        comment="渠道用途说明",
    )

    __table_args__ = (
        Index(
            "ix_notification_channels_profile_kind",
            "profile_id",
            "kind",
        ),
    )


class NotificationDelivery(Base, TimestampMixin):
    """通知投递日志（仅记录失败）。

    设计要点：
        - 成功投递只走 ``logger.info``，不进表，避免高频写放大；
        - 失败（重试 3 次仍未成功）才入表，承载"事后取证"职责；
        - ``finding_id`` 用 nullable Integer 引用，但**不**建 FK：
          dispatcher 是异步 BackgroundTasks，写日志时上层事务已提交，
          建 FK 反而带来跨事务约束麻烦；
        - ``error`` 用 ``Text`` 而非 ``String``，方便存堆栈。
    """

    __tablename__ = "notification_deliveries"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    channel_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="对应 NotificationChannel.id",
    )
    finding_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
        comment="触发的 ComplianceFinding.id（可空，便于其他场景复用）",
    )
    kind: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="渠道类型快照：slack / email",
    )
    target: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        comment="投递目标快照（webhook URL 或 email）",
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="累计尝试次数（含首次）",
    )
    error: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
        comment="最后一次失败的错误描述",
    )
    failed_at: Mapped[datetime] = mapped_column(
        nullable=False,
        comment="最后失败时间（UTC）",
    )


__all__ = [
    "NotificationChannel",
    "NotificationDelivery",
]
