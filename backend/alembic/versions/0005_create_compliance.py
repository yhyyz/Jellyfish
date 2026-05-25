"""0005 - 创建合规管理相关 2 张表（W2-T3 配套迁移）。

新增表：

- ``compliance_profiles``：合规规则集（按地域+品类分组）；
- ``compliance_findings``：单次合规检查的具体问题（每个 ``StoryVariant``
  可关联 N 条），通过外键 ON DELETE CASCADE 跟随变体清理。

联合索引 ``ix_compliance_findings_variant_severity (variant_id, severity)``
用于"按变体快速过滤 blocker"这类常用查询。

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-25
"""

# pylint: disable=invalid-name,no-member

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 compliance_profiles / compliance_findings 两张表。"""
    # === compliance_profiles ===
    op.create_table(
        "compliance_profiles",
        sa.Column(
            "id",
            sa.String(length=64),
            primary_key=True,
            comment="profile ID",
        ),
        sa.Column(
            "name", sa.String(length=255), nullable=False, comment="显示名称"
        ),
        sa.Column(
            "region",
            sa.String(length=16),
            nullable=False,
            server_default="cn_mainland",
            comment="适用地域",
        ),
        sa.Column(
            "rules",
            sa.JSON(),
            nullable=False,
            comment="规则数组 JSON",
        ),
        sa.Column(
            "is_system",
            sa.Boolean(),
            nullable=False,
            server_default="1",
            comment="系统预置",
        ),
        sa.Column(
            "description",
            sa.Text(),
            nullable=False,
            server_default="",
            comment="profile 用途说明",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        comment="合规规则集（按地域+品类分组）",
    )
    op.create_index(
        "ix_compliance_profiles_region", "compliance_profiles", ["region"]
    )

    # === compliance_findings ===
    op.create_table(
        "compliance_findings",
        sa.Column(
            "id", sa.Integer(), primary_key=True, autoincrement=True
        ),
        sa.Column(
            "variant_id",
            sa.String(length=64),
            sa.ForeignKey("story_variants.id", ondelete="CASCADE"),
            nullable=False,
            comment="所属脚本变体",
        ),
        sa.Column(
            "severity",
            sa.String(length=16),
            nullable=False,
            server_default="warning",
            comment="严重度",
        ),
        sa.Column(
            "rule_id",
            sa.String(length=64),
            nullable=False,
            comment="触发的规则 ID",
        ),
        sa.Column(
            "rule_kind",
            sa.String(length=32),
            nullable=False,
            server_default="banned_phrase",
            comment="规则类型",
        ),
        sa.Column(
            "description", sa.Text(), nullable=False, comment="问题描述"
        ),
        sa.Column(
            "location",
            sa.String(length=255),
            nullable=True,
            comment="脚本中位置",
        ),
        sa.Column(
            "suggested_fix",
            sa.Text(),
            nullable=True,
            comment="建议修复方案",
        ),
        sa.Column(
            "is_resolved",
            sa.Boolean(),
            nullable=False,
            server_default="0",
            comment="是否已解决",
        ),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="检测时间",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        comment="合规检查产出的具体问题",
    )
    op.create_index(
        "ix_compliance_findings_variant_id",
        "compliance_findings",
        ["variant_id"],
    )
    op.create_index(
        "ix_compliance_findings_severity",
        "compliance_findings",
        ["severity"],
    )
    op.create_index(
        "ix_compliance_findings_rule_id", "compliance_findings", ["rule_id"]
    )
    op.create_index(
        "ix_compliance_findings_is_resolved",
        "compliance_findings",
        ["is_resolved"],
    )
    # 联合索引：按变体过滤 + 按严重度筛 blocker 的常用查询。
    op.create_index(
        "ix_compliance_findings_variant_severity",
        "compliance_findings",
        ["variant_id", "severity"],
    )


def downgrade() -> None:
    """按依赖反序删除两张表。"""
    op.drop_index(
        "ix_compliance_findings_variant_severity",
        table_name="compliance_findings",
    )
    op.drop_index(
        "ix_compliance_findings_is_resolved", table_name="compliance_findings"
    )
    op.drop_index(
        "ix_compliance_findings_rule_id", table_name="compliance_findings"
    )
    op.drop_index(
        "ix_compliance_findings_severity", table_name="compliance_findings"
    )
    op.drop_index(
        "ix_compliance_findings_variant_id", table_name="compliance_findings"
    )
    op.drop_table("compliance_findings")

    op.drop_index(
        "ix_compliance_profiles_region", table_name="compliance_profiles"
    )
    op.drop_table("compliance_profiles")
