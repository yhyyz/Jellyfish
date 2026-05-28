"""0013 - W25-T3 BrandStyleGuide 1:1 per-Product 配套迁移。

为 P4 Wave A "品牌话术规范库" 引入新表 :class:`BrandStyleGuide`：

* ``product_id`` 既是 FK（→ ``products.id`` ``ON DELETE CASCADE``），又是
  ``UNIQUE``，等价于 "至多一份规范挂在某个商品上"，与 D-BRAND-SCOPE 决策
  ("per-Product 1:1 optional FK") 对齐。
* 4 个 JSON list 字段 + 1 个 ``brand_persona_tagline`` 字符串，承载强制
  金句 / 禁用句式 / 必备结尾 / 品牌人格短描述。

设计要点：

* 仅新增一张表，不动 ``products`` / 其他 commerce 表（与任务 FORBIDDEN
  保持一致：本任务不动 Product model）。
* 与现有 0007 / 0011 模式一致：``id`` ``VARCHAR(64)``，时间戳两列加
  ``server_default=now()``，便于 SQLite / MySQL 兼容。
* down_revision 指向 ``0012``：本仓库当前 head 在 0011 → 0012 之后。
  本任务与 sibling 任务（T25-1/T25-2/W23-T1）并行；migration 链最终由集成
  阶段统一 rebase，0014 / 后续序号若被其他 sibling 占用，本文件保留 0013
  文件名以避免 re-numbering 冲突。

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-28
"""

# pylint: disable=invalid-name,no-member

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0013"
down_revision: Union[str, Sequence[str], None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 ``brand_style_guides`` 表。"""
    op.create_table(
        "brand_style_guides",
        sa.Column(
            "id",
            sa.String(length=64),
            primary_key=True,
            comment="规范 ID（uuid4 hex，由 service 层生成）",
        ),
        sa.Column(
            "product_id",
            sa.String(length=64),
            sa.ForeignKey(
                "products.id",
                name="fk_brand_style_guides_product_id",
                ondelete="CASCADE",
            ),
            nullable=False,
            comment="所属商品 ID（1:1，UNIQUE + CASCADE）",
        ),
        sa.Column(
            "forced_phrases",
            sa.JSON(),
            nullable=False,
            comment="强制金句列表（生成器必须包含的短语）",
        ),
        sa.Column(
            "banned_patterns",
            sa.JSON(),
            nullable=False,
            comment="禁用句式列表（生成器需回避的措辞）",
        ),
        sa.Column(
            "required_endings",
            sa.JSON(),
            nullable=False,
            comment="必备结尾列表（CTA / 免责声明类强制收口短语）",
        ),
        sa.Column(
            "brand_persona_tagline",
            sa.String(length=255),
            nullable=False,
            server_default="",
            comment="品牌人格短描述（一句话 tagline）",
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
        sa.UniqueConstraint(
            "product_id",
            name="uq_brand_style_guides_product_id",
        ),
        comment="品牌话术规范库（与 Product 1:1 可选）",
    )
    op.create_index(
        "ix_brand_style_guides_product_id",
        "brand_style_guides",
        ["product_id"],
    )


def downgrade() -> None:
    """反向：先 drop 索引 → 再 drop 表。"""
    op.drop_index(
        "ix_brand_style_guides_product_id",
        table_name="brand_style_guides",
    )
    op.drop_table("brand_style_guides")
