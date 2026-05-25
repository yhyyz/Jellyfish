"""0006 - 创建 ``api_key_quotas`` 表（W2-T4 配套迁移）。

为 P3 阶段的 partner / 外部 API key 配额管理预留持久化结构。P1 阶段
仅建表，不暴露读写接口；主键直接采用 ``api_key_hash``（API key 的
bcrypt 哈希），避免持久化明文 key。

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-25
"""

# pylint: disable=invalid-name,no-member

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 ``api_key_quotas`` 表。"""
    op.create_table(
        "api_key_quotas",
        sa.Column(
            "api_key_hash",
            sa.String(length=128),
            primary_key=True,
            comment="API key 的 bcrypt 哈希（PK）",
        ),
        sa.Column(
            "daily_limit",
            sa.Integer(),
            nullable=False,
            server_default="1000",
            comment="日调用上限",
        ),
        sa.Column(
            "monthly_limit",
            sa.Integer(),
            nullable=False,
            server_default="30000",
            comment="月调用上限",
        ),
        sa.Column(
            "rate_per_minute",
            sa.Integer(),
            nullable=False,
            server_default="60",
            comment="每分钟请求数上限",
        ),
        sa.Column(
            "consumed_today",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="今日已消耗",
        ),
        sa.Column(
            "consumed_this_month",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="本月已消耗",
        ),
        sa.Column(
            "last_reset_daily",
            sa.Date(),
            nullable=False,
            comment="上次日重置日期",
        ),
        sa.Column(
            "last_reset_monthly",
            sa.Date(),
            nullable=False,
            comment="上次月重置日期",
        ),
        sa.Column(
            "description",
            sa.String(length=255),
            nullable=False,
            server_default="",
            comment="key 用途备注",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default="1",
            comment="是否启用",
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
        comment="API key 配额记录（P3 启用 partner API 时使用，P1 仅建表预留）",
    )
    op.create_index(
        "ix_api_key_quotas_is_active", "api_key_quotas", ["is_active"]
    )


def downgrade() -> None:
    """删除 ``api_key_quotas`` 表。"""
    op.drop_index("ix_api_key_quotas_is_active", table_name="api_key_quotas")
    op.drop_table("api_key_quotas")
