"""0003 - 创建剧情带货商品资产相关表（W2-T1 配套迁移）。

新增 4 张表，承载"商品（Product）"作为剧情带货核心资源的全套数据：

- ``products``：商品主体（全库 ``name`` 唯一）；
- ``product_images``：多角度商品图（按 quality/view 唯一）；
- ``project_product_links``：项目-章节-镜头三层粒度的商品挂载；
- ``commerce_story_configs``：项目级带货专属配置（与 Project 1:1）。

所有外键显式声明 ``ondelete``，与 SQLAlchemy 模型层一一对应。

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-25
"""

# pylint: disable=invalid-name,no-member

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建商品/商品图/项目-商品关联/带货配置 4 张表。"""
    # === products ===
    op.create_table(
        "products",
        sa.Column("id", sa.String(length=64), primary_key=True, comment="商品唯一标识"),
        sa.Column("name", sa.String(length=255), nullable=False, comment="商品名称"),
        sa.Column(
            "brand",
            sa.String(length=128),
            nullable=False,
            server_default="",
            comment="品牌",
        ),
        sa.Column(
            "category",
            sa.String(length=32),
            nullable=False,
            server_default="other",
            comment="商品分类（电子/美妆/食品/服饰/家居/健康/其他）",
        ),
        sa.Column(
            "description",
            sa.Text(),
            nullable=False,
            server_default="",
            comment="商品描述/卖点摘要",
        ),
        sa.Column("price_anchor", sa.Float(), nullable=True, comment="锚定价（人民币）"),
        sa.Column("sku", sa.String(length=64), nullable=True, comment="SKU / 货号"),
        sa.Column(
            "selling_points",
            sa.JSON(),
            nullable=False,
            comment="卖点列表（JSON 数组，建议 ≤5）",
        ),
        sa.Column(
            "pain_points_solved",
            sa.JSON(),
            nullable=False,
            comment="解决的痛点（JSON 数组）",
        ),
        sa.Column(
            "target_audience",
            sa.JSON(),
            nullable=False,
            comment="目标受众 JSON",
        ),
        sa.Column("catchphrases", sa.JSON(), nullable=False, comment="金句台词列表"),
        sa.Column(
            "competitor_names",
            sa.JSON(),
            nullable=False,
            comment="禁止提及的竞品名列表",
        ),
        sa.Column(
            "health_disclaimer_required",
            sa.Boolean(),
            nullable=False,
            server_default="0",
            comment="是否需要健康类免责声明",
        ),
        sa.Column(
            "visual_style",
            sa.String(length=16),
            nullable=False,
            server_default="现实",
            comment="视觉风格",
        ),
        sa.Column(
            "style",
            sa.String(length=32),
            nullable=False,
            server_default="真人都市",
            comment="题材风格",
        ),
        sa.Column(
            "prompt_template_id",
            sa.String(length=64),
            sa.ForeignKey("prompt_templates.id", ondelete="SET NULL"),
            nullable=True,
            comment="关联提示词模板 ID",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("name", name="uq_products_name"),
        comment="剧情带货商品主体表（D1：name 全库唯一）",
    )
    op.create_index("ix_products_name", "products", ["name"])
    op.create_index("ix_products_category", "products", ["category"])
    op.create_index(
        "ix_products_prompt_template_id", "products", ["prompt_template_id"]
    )

    # === product_images ===
    op.create_table(
        "product_images",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
            comment="自增主键",
        ),
        sa.Column(
            "product_id",
            sa.String(length=64),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
            comment="所属商品 ID",
        ),
        sa.Column(
            "file_id",
            sa.String(length=64),
            sa.ForeignKey("files.id", ondelete="CASCADE"),
            nullable=True,
            comment="关联文件 ID",
        ),
        sa.Column(
            "quality_level",
            sa.String(length=16),
            nullable=False,
            server_default="LOW",
            comment="质量等级（LOW/MEDIUM/HIGH/ULTRA）",
        ),
        sa.Column(
            "view_angle",
            sa.String(length=32),
            nullable=False,
            server_default="FRONT",
            comment="视角（FRONT/LEFT/RIGHT/...）",
        ),
        sa.Column(
            "is_primary",
            sa.Boolean(),
            nullable=False,
            server_default="0",
            comment="是否主图",
        ),
        sa.Column("width", sa.Integer(), nullable=True, comment="宽（像素）"),
        sa.Column("height", sa.Integer(), nullable=True, comment="高（像素）"),
        sa.Column("fmt", sa.String(length=16), nullable=True, comment="格式"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "product_id",
            "quality_level",
            "view_angle",
            name="uq_product_images_quality_angle",
        ),
        comment="商品多角度图片",
    )
    op.create_index(
        "ix_product_images_product_id", "product_images", ["product_id"]
    )
    op.create_index("ix_product_images_file_id", "product_images", ["file_id"])
    op.create_index(
        "ix_product_images_quality_level", "product_images", ["quality_level"]
    )
    op.create_index(
        "ix_product_images_view_angle", "product_images", ["view_angle"]
    )

    # === project_product_links ===
    op.create_table(
        "project_product_links",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
            comment="自增主键",
        ),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            comment="项目 ID",
        ),
        sa.Column(
            "chapter_id",
            sa.String(length=64),
            sa.ForeignKey("chapters.id", ondelete="SET NULL"),
            nullable=True,
            comment="章节 ID",
        ),
        sa.Column(
            "shot_id",
            sa.String(length=64),
            sa.ForeignKey("shots.id", ondelete="SET NULL"),
            nullable=True,
            comment="镜头 ID",
        ),
        sa.Column(
            "product_id",
            sa.String(length=64),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
            comment="商品 ID",
        ),
        sa.Column(
            "role_in_story",
            sa.String(length=32),
            nullable=False,
            server_default="savior",
            comment="商品在剧情中的角色",
        ),
        sa.Column(
            "appearance_timing",
            sa.String(length=16),
            nullable=False,
            server_default="middle",
            comment="出现时机",
        ),
        sa.Column(
            "appearance_duration_sec",
            sa.Integer(),
            nullable=False,
            server_default="5",
            comment="出现时长（秒）",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "product_id",
            "project_id",
            "chapter_id",
            "shot_id",
            name="uq_project_product_links_scope",
        ),
        comment="项目-商品多对多关联（可挂在 project/chapter/shot 任一层）",
    )
    op.create_index(
        "ix_project_product_links_project_id",
        "project_product_links",
        ["project_id"],
    )
    op.create_index(
        "ix_project_product_links_chapter_id",
        "project_product_links",
        ["chapter_id"],
    )
    op.create_index(
        "ix_project_product_links_shot_id", "project_product_links", ["shot_id"]
    )
    op.create_index(
        "ix_project_product_links_product_id",
        "project_product_links",
        ["product_id"],
    )

    # === commerce_story_configs ===
    op.create_table(
        "commerce_story_configs",
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
            comment="项目 ID（PK，1:1）",
        ),
        sa.Column(
            "target_platform",
            sa.String(length=32),
            nullable=False,
            server_default="douyin",
            comment="目标平台",
        ),
        sa.Column(
            "target_duration_sec",
            sa.Integer(),
            nullable=False,
            server_default="60",
            comment="目标时长（秒）",
        ),
        sa.Column(
            "formula_id",
            sa.String(length=64),
            nullable=True,
            comment="选定的剧情公式 ID",
        ),
        sa.Column(
            "archetype",
            sa.String(length=32),
            nullable=True,
            comment="品牌人格 archetype",
        ),
        sa.Column(
            "tone_grid", sa.JSON(), nullable=False, comment="语调维度 JSON"
        ),
        sa.Column(
            "audience_override",
            sa.JSON(),
            nullable=True,
            comment="覆盖商品默认受众的项目级配置",
        ),
        sa.Column(
            "compliance_region",
            sa.String(length=16),
            nullable=False,
            server_default="cn_mainland",
            comment="合规地域",
        ),
        sa.Column(
            "compliance_profile_id",
            sa.String(length=64),
            nullable=False,
            server_default="cn_mainland_default",
            comment="合规规则集 ID",
        ),
        sa.Column(
            "target_kpi",
            sa.String(length=32),
            nullable=True,
            comment="目标 KPI: awareness/clicks/conversion",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        comment="剧情带货项目专属配置（与 Project 1:1）",
    )
    op.create_index(
        "ix_commerce_story_configs_formula_id",
        "commerce_story_configs",
        ["formula_id"],
    )


def downgrade() -> None:
    """按依赖反序删除 4 张表。"""
    op.drop_index(
        "ix_commerce_story_configs_formula_id",
        table_name="commerce_story_configs",
    )
    op.drop_table("commerce_story_configs")

    op.drop_index(
        "ix_project_product_links_product_id",
        table_name="project_product_links",
    )
    op.drop_index(
        "ix_project_product_links_shot_id", table_name="project_product_links"
    )
    op.drop_index(
        "ix_project_product_links_chapter_id",
        table_name="project_product_links",
    )
    op.drop_index(
        "ix_project_product_links_project_id",
        table_name="project_product_links",
    )
    op.drop_table("project_product_links")

    op.drop_index("ix_product_images_view_angle", table_name="product_images")
    op.drop_index(
        "ix_product_images_quality_level", table_name="product_images"
    )
    op.drop_index("ix_product_images_file_id", table_name="product_images")
    op.drop_index("ix_product_images_product_id", table_name="product_images")
    op.drop_table("product_images")

    op.drop_index("ix_products_prompt_template_id", table_name="products")
    op.drop_index("ix_products_category", table_name="products")
    op.drop_index("ix_products_name", table_name="products")
    op.drop_table("products")
