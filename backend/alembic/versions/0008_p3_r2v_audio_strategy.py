"""0008 - shots 表新增 audio_strategy 与 product_focus_level 列（W16 T16-8 配套迁移）。

为 P3 R2V 阶段引入两个新概念：

- audio_strategy（Decision D）：silent_with_tts（默认）/ keep_native，
  决定视频生成时是否保留模型自带原音；默认走静音 + TTS 合成对白以
  保证口播节奏与质量可控。
- product_focus_level（Decision H）：subtle / functional / hero / none，
  决定 r2v 多图参考的角度优先级序列；none 表示该镜头没有商品出现，
  应走纯文生视频（t2v）而非多图参考。

存量数据 backfill：旧 shots 默认 audio_strategy='silent_with_tts'、
product_focus_level='none'，由列级 server_default 自动覆盖，迁移本身
无需额外 UPDATE 语句。

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-26
"""

# pylint: disable=invalid-name,no-member

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新增 ``audio_strategy`` 与 ``product_focus_level`` 列至 ``shots`` 表。

    两列均为 ``NOT NULL`` 配 ``server_default``，存量行将通过 default 自动
    回填为 ``silent_with_tts`` / ``none``，确保历史镜头不会因新列引入而
    出现 NULL 违约。
    """
    op.add_column(
        "shots",
        sa.Column(
            "audio_strategy",
            sa.String(length=32),
            nullable=False,
            server_default="silent_with_tts",
            comment="镜头音频策略：silent_with_tts（默认）/ keep_native（保留原音）",
        ),
    )
    op.add_column(
        "shots",
        sa.Column(
            "product_focus_level",
            sa.String(length=16),
            nullable=False,
            server_default="none",
            comment="商品视觉聚焦级别：subtle/functional/hero/none（Decision H）",
        ),
    )


def downgrade() -> None:
    """回滚：按新增反序移除两个列，使 ``shots`` 表回到 0007 形态。"""
    op.drop_column("shots", "product_focus_level")
    op.drop_column("shots", "audio_strategy")
