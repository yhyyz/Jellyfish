"""0007 - 创建模式库 3 张表（W11-T2 配套迁移）。

新增表：

- ``hook_patterns``：钩子模式库（10 条系统级，question/conflict/contrast/...）；
- ``cta_patterns``：CTA 模式库（5 条系统级，按 hardness × urgency_type 划分）；
- ``brand_archetypes``：品牌人格原型库（12 条，与 tonethief 词汇表对齐）。

设计要点：

- 三张表均为系统级注册表（``is_system`` 默认 ``True``），由
  ``app.bootstrap.bootstrap_async_state`` 在启动期幂等写入；
- 主键统一为 ``VARCHAR(64)``，``brand_archetypes.id`` 同时作为
  ``BrandArchetype`` 枚举值（如 ``sage`` / ``jester``），便于与
  ``commerce_story_configs.archetype`` 字段共享词汇表；
- 与 ``story_variants.hook_pattern_id`` / ``cta_pattern_id`` 字段保持
  字符串解耦：W11-T2 阶段不为 ``story_variants`` 增加硬外键，留待 P2
  钩子/CTA 模式库联调阶段（Wave 13/14）再决定是否升级为 ``ON DELETE
  RESTRICT``；
- 索引仅覆盖 UI 列表筛选与排序所需字段（``pattern_type`` / ``hardness``
  / ``urgency_type`` / ``sort_order``），避免冗余索引带来的写入开销。

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-25
"""

# pylint: disable=invalid-name,no-member

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 hook_patterns / cta_patterns / brand_archetypes 三张表。"""
    # === hook_patterns =====================================================
    op.create_table(
        "hook_patterns",
        sa.Column(
            "id",
            sa.String(length=64),
            primary_key=True,
            comment="钩子 ID（如 question_hook / conflict_hook）",
        ),
        sa.Column(
            "name",
            sa.String(length=255),
            nullable=False,
            comment="中文名称（如 问句钩子）",
        ),
        sa.Column(
            "pattern_type",
            sa.String(length=32),
            nullable=False,
            comment="钩子类型：question / conflict / contrast / ...",
        ),
        sa.Column(
            "description",
            sa.Text(),
            nullable=False,
            comment="钩子说明（运营/UI 展示）",
        ),
        sa.Column(
            "template_text",
            sa.Text(),
            nullable=False,
            comment="Jinja2 模板片段，LLM 渲染开场用",
        ),
        sa.Column(
            "psychology",
            sa.Text(),
            nullable=False,
            comment="心理学原理：为什么这种钩子有效",
        ),
        sa.Column(
            "use_cases",
            sa.JSON(),
            nullable=False,
            comment="适用场景列表",
        ),
        sa.Column(
            "avoid_cases",
            sa.JSON(),
            nullable=False,
            comment="禁忌场景列表",
        ),
        sa.Column(
            "is_system",
            sa.Boolean(),
            nullable=False,
            server_default="1",
            comment="系统模板，不可删除",
        ),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="UI 显示排序（升序）",
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
        comment="钩子模式库（系统级，P2 启用）",
    )
    op.create_index(
        "ix_hook_patterns_pattern_type", "hook_patterns", ["pattern_type"]
    )
    op.create_index(
        "ix_hook_patterns_sort_order", "hook_patterns", ["sort_order"]
    )

    # === cta_patterns ======================================================
    op.create_table(
        "cta_patterns",
        sa.Column(
            "id",
            sa.String(length=64),
            primary_key=True,
            comment="CTA ID（如 scarcity_cta / social_proof_cta）",
        ),
        sa.Column(
            "name",
            sa.String(length=255),
            nullable=False,
            comment="中文名称（如 稀缺紧迫）",
        ),
        sa.Column(
            "hardness",
            sa.String(length=16),
            nullable=False,
            comment="硬度等级：soft / medium / hard",
        ),
        sa.Column(
            "urgency_type",
            sa.String(length=32),
            nullable=False,
            comment="驱动类型：scarcity / urgency / social_proof / benefit / risk_removal",
        ),
        sa.Column(
            "description",
            sa.Text(),
            nullable=False,
            comment="CTA 说明（运营/UI 展示）",
        ),
        sa.Column(
            "template_text",
            sa.Text(),
            nullable=False,
            comment="Jinja2 模板片段，LLM 渲染收尾用",
        ),
        sa.Column(
            "sample_phrases",
            sa.JSON(),
            nullable=False,
            comment="样例 CTA 短语列表（5-10 条）",
        ),
        sa.Column(
            "is_system",
            sa.Boolean(),
            nullable=False,
            server_default="1",
            comment="系统模板，不可删除",
        ),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="UI 显示排序（升序）",
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
        comment="CTA 模式库（系统级，P2 启用）",
    )
    op.create_index(
        "ix_cta_patterns_hardness", "cta_patterns", ["hardness"]
    )
    op.create_index(
        "ix_cta_patterns_urgency_type", "cta_patterns", ["urgency_type"]
    )

    # === brand_archetypes ==================================================
    op.create_table(
        "brand_archetypes",
        sa.Column(
            "id",
            sa.String(length=64),
            primary_key=True,
            comment="原型 ID（与 BrandArchetype 枚举值同名，如 sage / jester）",
        ),
        sa.Column(
            "name",
            sa.String(length=255),
            nullable=False,
            comment="英文名称（Sage / Jester / ...）",
        ),
        sa.Column(
            "name_zh",
            sa.String(length=64),
            nullable=False,
            comment="中文名称（智者 / 小丑 / ...）",
        ),
        sa.Column(
            "motivation",
            sa.Text(),
            nullable=False,
            comment="核心动机（why this archetype exists）",
        ),
        sa.Column(
            "voice_traits",
            sa.JSON(),
            nullable=False,
            comment="语调描述符列表（5-10 个形容词）",
        ),
        sa.Column(
            "speech_patterns",
            sa.JSON(),
            nullable=False,
            comment="语言模式 JSON：{do: [...], dont: [...]}",
        ),
        sa.Column(
            "sample_brands",
            sa.JSON(),
            nullable=False,
            comment="代表品牌列表（3-5 个真实品牌）",
        ),
        sa.Column(
            "is_system",
            sa.Boolean(),
            nullable=False,
            server_default="1",
            comment="系统原型，不可删除",
        ),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="UI 显示排序（升序）",
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
        comment="品牌人格原型库（系统级，与 BrandArchetype 枚举共享词汇表）",
    )
    op.create_index(
        "ix_brand_archetypes_sort_order", "brand_archetypes", ["sort_order"]
    )


def downgrade() -> None:
    """按依赖反序删除三张表（彼此独立，顺序仅为可读性）。"""
    op.drop_index(
        "ix_brand_archetypes_sort_order", table_name="brand_archetypes"
    )
    op.drop_table("brand_archetypes")

    op.drop_index("ix_cta_patterns_urgency_type", table_name="cta_patterns")
    op.drop_index("ix_cta_patterns_hardness", table_name="cta_patterns")
    op.drop_table("cta_patterns")

    op.drop_index("ix_hook_patterns_sort_order", table_name="hook_patterns")
    op.drop_index("ix_hook_patterns_pattern_type", table_name="hook_patterns")
    op.drop_table("hook_patterns")
