"""0014 - W26-T1 合规 BLOCKER 告警通知子系统建表。

新增两张表（直接配套 :mod:`app.models.notification_channel`）：

- ``notification_channels``：合规告警渠道配置（Slack / email），可按
  :class:`ComplianceProfile` 绑定，也可作为全局兜底（``profile_id=NULL``）。
- ``notification_deliveries``：投递日志，**只记录失败**（重试 3 次仍未
  成功）；不对 ``compliance_findings`` 建 FK，避免与异步 BackgroundTasks
  路径下的事务边界冲突。

设计要点：

- ``notification_channels.profile_id`` 走 ``ON DELETE SET NULL``：profile
  被删除时渠道降级为全局兜底，而不是被静默清掉。
- ``notification_channels`` 上建 ``(profile_id, kind)`` 联合索引，便于
  dispatcher 的 "按 profile 取所有 enabled 渠道" 查询。
- ``notification_deliveries`` 不引入跨表 FK：``finding_id`` / ``channel_id``
  都用裸列 + 索引引用，因为 dispatcher 走 BackgroundTasks，写日志时
  上层事务可能已提交，FK 约束反而成阻碍。

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-28
"""

# pylint: disable=invalid-name,no-member

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0014"
down_revision: Union[str, Sequence[str], None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 notification_channels / notification_deliveries 两张表。"""
    op.create_table(
        "notification_channels",
        sa.Column(
            "id",
            sa.String(length=64),
            primary_key=True,
            comment="稳定字符串 ID",
        ),
        sa.Column(
            "profile_id",
            sa.String(length=64),
            sa.ForeignKey(
                "compliance_profiles.id",
                name="fk_notification_channels_profile_id",
                ondelete="SET NULL",
            ),
            nullable=True,
            comment="可选关联到某个合规 profile；NULL=全局兜底渠道",
        ),
        sa.Column(
            "kind",
            sa.String(length=16),
            nullable=False,
            comment="渠道类型：slack / email",
        ),
        sa.Column(
            "target",
            sa.String(length=512),
            nullable=False,
            comment="Slack webhook URL 或 email 收件人地址",
        ),
        sa.Column(
            "secret_ref",
            sa.String(length=255),
            nullable=True,
            comment="可选 secret manager 引用别名",
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default="1",
            comment="是否启用",
        ),
        sa.Column(
            "description",
            sa.Text(),
            nullable=False,
            server_default="",
            comment="渠道用途说明",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        comment="合规告警通知渠道（W26-T1）",
    )
    op.create_index(
        "ix_notification_channels_profile_id",
        "notification_channels",
        ["profile_id"],
    )
    op.create_index(
        "ix_notification_channels_kind",
        "notification_channels",
        ["kind"],
    )
    op.create_index(
        "ix_notification_channels_profile_kind",
        "notification_channels",
        ["profile_id", "kind"],
    )

    op.create_table(
        "notification_deliveries",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "channel_id",
            sa.String(length=64),
            nullable=False,
            comment="对应 NotificationChannel.id",
        ),
        sa.Column(
            "finding_id",
            sa.Integer(),
            nullable=True,
            comment="触发的 ComplianceFinding.id（可空）",
        ),
        sa.Column(
            "kind",
            sa.String(length=16),
            nullable=False,
            comment="渠道类型快照：slack / email",
        ),
        sa.Column(
            "target",
            sa.String(length=512),
            nullable=False,
            comment="投递目标快照",
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="累计尝试次数",
        ),
        sa.Column(
            "error",
            sa.Text(),
            nullable=False,
            server_default="",
            comment="最后一次失败的错误描述",
        ),
        sa.Column(
            "failed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="最后失败时间（UTC）",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        comment="通知投递失败日志（W26-T1）",
    )
    op.create_index(
        "ix_notification_deliveries_channel_id",
        "notification_deliveries",
        ["channel_id"],
    )
    op.create_index(
        "ix_notification_deliveries_finding_id",
        "notification_deliveries",
        ["finding_id"],
    )


def downgrade() -> None:
    """反向：drop 索引 → drop 表。"""
    op.drop_index(
        "ix_notification_deliveries_finding_id",
        table_name="notification_deliveries",
    )
    op.drop_index(
        "ix_notification_deliveries_channel_id",
        table_name="notification_deliveries",
    )
    op.drop_table("notification_deliveries")

    op.drop_index(
        "ix_notification_channels_profile_kind",
        table_name="notification_channels",
    )
    op.drop_index(
        "ix_notification_channels_kind",
        table_name="notification_channels",
    )
    op.drop_index(
        "ix_notification_channels_profile_id",
        table_name="notification_channels",
    )
    op.drop_table("notification_channels")
