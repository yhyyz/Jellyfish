"""0004 - 创建剧情公式相关 3 张表（W2-T2 配套迁移）。

新增表：

- ``story_formulas``：系统级剧情公式注册表（``is_system=True`` 系统预置）；
- ``story_variants``：项目/章节下的脚本变体（用于 A/B 测试）；
- ``story_outcomes``：脚本变体的真实投放效果（``plays`` 使用 ``BigInteger``
  避免爆款溢出 ``2^31``）。

外键策略：

- ``story_variants.project_id`` → ``projects.id`` ON DELETE CASCADE
- ``story_variants.chapter_id`` → ``chapters.id`` ON DELETE CASCADE
- ``story_variants.formula_id`` → ``story_formulas.id`` ON DELETE RESTRICT
- ``story_formulas.prompt_template_id`` → ``prompt_templates.id`` RESTRICT
- ``story_outcomes.variant_id`` → ``story_variants.id`` ON DELETE CASCADE

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-25
"""

# pylint: disable=invalid-name,no-member

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 story_formulas / story_variants / story_outcomes 三张表。"""
    # === story_formulas ===
    op.create_table(
        "story_formulas",
        sa.Column(
            "id",
            sa.String(length=64),
            primary_key=True,
            comment="公式 ID（如 underdog_triumph）",
        ),
        sa.Column("name", sa.String(length=255), nullable=False, comment="中文名称"),
        sa.Column(
            "region",
            sa.String(length=16),
            nullable=False,
            server_default="cn",
            comment="适用地域：cn / global",
        ),
        sa.Column(
            "category",
            sa.String(length=64),
            nullable=False,
            server_default="cn_viral",
            comment="分类标签",
        ),
        sa.Column(
            "structure",
            sa.JSON(),
            nullable=False,
            comment="完整 beat 结构 JSON",
        ),
        sa.Column(
            "risk_flags", sa.JSON(), nullable=False, comment="风险标记数组"
        ),
        sa.Column(
            "sample_dialog",
            sa.Text(),
            nullable=False,
            server_default="",
            comment="完整示例剧本",
        ),
        sa.Column(
            "typical_duration_sec",
            sa.Integer(),
            nullable=False,
            server_default="60",
            comment="典型时长（秒）",
        ),
        sa.Column(
            "typical_shot_count",
            sa.Integer(),
            nullable=False,
            server_default="4",
            comment="典型镜头数",
        ),
        sa.Column(
            "psychology",
            sa.Text(),
            nullable=False,
            server_default="",
            comment="心理学原理",
        ),
        sa.Column("use_cases", sa.JSON(), nullable=False, comment="适用场景"),
        sa.Column(
            "avoid_cases", sa.JSON(), nullable=False, comment="禁忌场景"
        ),
        sa.Column(
            "prompt_template_id",
            sa.String(length=64),
            sa.ForeignKey("prompt_templates.id", ondelete="RESTRICT"),
            nullable=False,
            comment="绑定的提示词模板",
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
            comment="UI 显示排序",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        comment="剧情公式注册表（系统级）",
    )
    op.create_index("ix_story_formulas_region", "story_formulas", ["region"])
    op.create_index(
        "ix_story_formulas_category", "story_formulas", ["category"]
    )
    op.create_index(
        "ix_story_formulas_prompt_template_id",
        "story_formulas",
        ["prompt_template_id"],
    )
    op.create_index(
        "ix_story_formulas_sort_order", "story_formulas", ["sort_order"]
    )
    # 联合筛选索引：region + category 是前端公式列表筛选的主入口。
    op.create_index(
        "ix_story_formulas_region_category",
        "story_formulas",
        ["region", "category"],
    )

    # === story_variants ===
    op.create_table(
        "story_variants",
        sa.Column(
            "id",
            sa.String(length=64),
            primary_key=True,
            comment="变体唯一 ID",
        ),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            comment="所属项目",
        ),
        sa.Column(
            "chapter_id",
            sa.String(length=64),
            sa.ForeignKey("chapters.id", ondelete="CASCADE"),
            nullable=False,
            comment="所属章节",
        ),
        sa.Column(
            "formula_id",
            sa.String(length=64),
            sa.ForeignKey("story_formulas.id", ondelete="RESTRICT"),
            nullable=False,
            comment="使用的剧情公式",
        ),
        sa.Column(
            "hook_pattern_id",
            sa.String(length=64),
            nullable=True,
            comment="钩子模式 ID（P2）",
        ),
        sa.Column(
            "cta_pattern_id",
            sa.String(length=64),
            nullable=True,
            comment="CTA 模式 ID（P2）",
        ),
        sa.Column(
            "archetype",
            sa.String(length=32),
            nullable=True,
            comment="品牌人格（P2）",
        ),
        sa.Column(
            "script_full_text",
            sa.Text(),
            nullable=False,
            server_default="",
            comment="完整剧本文本",
        ),
        sa.Column(
            "script_breakdown",
            sa.JSON(),
            nullable=False,
            comment="镜头分解结果 JSON",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="draft",
            comment="状态：draft / generating / ready / failed",
        ),
        sa.Column(
            "is_champion",
            sa.Boolean(),
            nullable=False,
            server_default="0",
            comment="是否冠军变体（P2）",
        ),
        sa.Column(
            "compliance_score",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="合规评分 0-100",
        ),
        sa.Column(
            "generated_by_task_id",
            sa.String(length=64),
            nullable=True,
            comment="生成此变体的 GenerationTask ID",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        comment="脚本变体（A/B 测试单元）",
    )
    op.create_index(
        "ix_story_variants_project_id", "story_variants", ["project_id"]
    )
    op.create_index(
        "ix_story_variants_chapter_id", "story_variants", ["chapter_id"]
    )
    op.create_index(
        "ix_story_variants_formula_id", "story_variants", ["formula_id"]
    )
    op.create_index(
        "ix_story_variants_hook_pattern_id",
        "story_variants",
        ["hook_pattern_id"],
    )
    op.create_index(
        "ix_story_variants_cta_pattern_id",
        "story_variants",
        ["cta_pattern_id"],
    )
    op.create_index("ix_story_variants_status", "story_variants", ["status"])
    op.create_index(
        "ix_story_variants_generated_by_task_id",
        "story_variants",
        ["generated_by_task_id"],
    )

    # === story_outcomes ===
    op.create_table(
        "story_outcomes",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
            comment="自增主键",
        ),
        sa.Column(
            "variant_id",
            sa.String(length=64),
            sa.ForeignKey("story_variants.id", ondelete="CASCADE"),
            nullable=False,
            comment="关联变体",
        ),
        sa.Column(
            "platform",
            sa.String(length=32),
            nullable=False,
            server_default="douyin",
            comment="投放平台",
        ),
        # BigInteger：爆款短视频播放量极易超过 2^31，避免后续再做迁移。
        sa.Column(
            "plays",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
            comment="播放量（BigInteger）",
        ),
        sa.Column(
            "completion_rate_3s",
            sa.Float(),
            nullable=True,
            comment="3 秒完播率（0~1）",
        ),
        sa.Column(
            "completion_rate_full",
            sa.Float(),
            nullable=True,
            comment="完整完播率（0~1）",
        ),
        sa.Column(
            "interactions",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="互动量（点赞+评论+分享）",
        ),
        sa.Column(
            "cart_clicks",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="加购点击",
        ),
        sa.Column(
            "orders",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="订单数",
        ),
        sa.Column(
            "gmv",
            sa.Float(),
            nullable=False,
            server_default="0",
            comment="GMV（人民币）",
        ),
        sa.Column(
            "notes",
            sa.Text(),
            nullable=False,
            server_default="",
            comment="备注",
        ),
        sa.Column(
            "raw_payload",
            sa.JSON(),
            nullable=False,
            comment="平台原始数据 JSON",
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="数据记录时点",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        comment="脚本变体的真实投放效果数据",
    )
    op.create_index(
        "ix_story_outcomes_variant_id", "story_outcomes", ["variant_id"]
    )
    op.create_index(
        "ix_story_outcomes_platform", "story_outcomes", ["platform"]
    )


def downgrade() -> None:
    """按依赖反序删除三张表。"""
    op.drop_index("ix_story_outcomes_platform", table_name="story_outcomes")
    op.drop_index("ix_story_outcomes_variant_id", table_name="story_outcomes")
    op.drop_table("story_outcomes")

    op.drop_index(
        "ix_story_variants_generated_by_task_id", table_name="story_variants"
    )
    op.drop_index("ix_story_variants_status", table_name="story_variants")
    op.drop_index(
        "ix_story_variants_cta_pattern_id", table_name="story_variants"
    )
    op.drop_index(
        "ix_story_variants_hook_pattern_id", table_name="story_variants"
    )
    op.drop_index("ix_story_variants_formula_id", table_name="story_variants")
    op.drop_index("ix_story_variants_chapter_id", table_name="story_variants")
    op.drop_index("ix_story_variants_project_id", table_name="story_variants")
    op.drop_table("story_variants")

    op.drop_index(
        "ix_story_formulas_region_category", table_name="story_formulas"
    )
    op.drop_index("ix_story_formulas_sort_order", table_name="story_formulas")
    op.drop_index(
        "ix_story_formulas_prompt_template_id", table_name="story_formulas"
    )
    op.drop_index("ix_story_formulas_category", table_name="story_formulas")
    op.drop_index("ix_story_formulas_region", table_name="story_formulas")
    op.drop_table("story_formulas")
