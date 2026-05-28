"""0016 - W26-T2 团队级 BLOCKER 升级状态建表。

新增 ``escalation_state`` 表，配套 :mod:`app.models.escalation_state`：

- 用稳定字符串主键 ``id`` 做 escalation engine 的 upsert key；
- ``profile_id`` 走 ``ON DELETE SET NULL``，profile 被删除时状态降级为
  全局口径，而非静默清掉计数；
- ``team_id`` 留 nullable 作前向兼容（当前无 Team 表）；
- ``window_start_at`` / ``last_escalated_at`` 都允许为空：状态首次创建时
  尚无窗口/触发记录。

设计要点：
- 不对 ``compliance_findings`` 建 FK：升级判定走 BackgroundTasks 异步路径，
  与 finding 写入跨事务；这里只存"窗口 + 计数器"快照，由 engine 做幂等
  upsert。

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-28
"""

# pylint: disable=invalid-name,no-member

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0016"
down_revision: Union[str, Sequence[str], None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 escalation_state 表。"""
    op.create_table(
        "escalation_state",
        sa.Column(
            "id",
            sa.String(length=64),
            primary_key=True,
            comment="稳定字符串 ID（profile:{profile_id} 或 __global__）",
        ),
        sa.Column(
            "profile_id",
            sa.String(length=64),
            sa.ForeignKey(
                "compliance_profiles.id",
                name="fk_escalation_state_profile_id",
                ondelete="SET NULL",
            ),
            nullable=True,
            comment="可选关联到合规 profile",
        ),
        sa.Column(
            "team_id",
            sa.String(length=64),
            nullable=True,
            comment="预留团队维度（当前无 Team 表）",
        ),
        sa.Column(
            "consecutive_blockers",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="当前窗口内已累计的 BLOCKER 次数",
        ),
        sa.Column(
            "window_start_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="当前计数窗口的起始时间",
        ),
        sa.Column(
            "last_escalated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="最近一次升级触发时间",
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
        comment="团队级 BLOCKER 升级状态计数器（W26-T2）",
    )
    op.create_index(
        "ix_escalation_state_profile_id",
        "escalation_state",
        ["profile_id"],
    )
    op.create_index(
        "ix_escalation_state_team_id",
        "escalation_state",
        ["team_id"],
    )
    op.create_index(
        "ix_escalation_state_profile_team",
        "escalation_state",
        ["profile_id", "team_id"],
    )


def downgrade() -> None:
    """反向：drop 索引 → drop 表。"""
    op.drop_index(
        "ix_escalation_state_profile_team",
        table_name="escalation_state",
    )
    op.drop_index(
        "ix_escalation_state_team_id",
        table_name="escalation_state",
    )
    op.drop_index(
        "ix_escalation_state_profile_id",
        table_name="escalation_state",
    )
    op.drop_table("escalation_state")
