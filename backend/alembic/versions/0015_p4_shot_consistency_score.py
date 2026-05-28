"""0015 - W27-T1 视觉一致性 score 列。

新增字段：

- ``shots.consistency_score``：``Float nullable``，由 ``shot_consistency_check``
  worker 写入。``NULL`` 显式表示 "未跑过 / 缺 reference / sidecar 不可达"，
  与数值 ``0.0`` 区分（cosine 0.0 是合法语义）。

设计要点：

- 使用 ``Float``（不锁精度），避免 MySQL / SQLite 之间的 ``DECIMAL`` 行为差异；
- 不建索引：本列只在写任务结果时更新，没有按 score 过滤的查询模式；后续
  W27-T2 threshold engine 走范围扫描时再考虑加索引。

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-28
"""

# pylint: disable=invalid-name,no-member

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0015"
down_revision: Union[str, Sequence[str], None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """向 ``shots`` 表追加 ``consistency_score`` 列。"""

    op.add_column(
        "shots",
        sa.Column(
            "consistency_score",
            sa.Float(),
            nullable=True,
            comment=(
                "DINOv2 ViT-B/14 视觉一致性得分（cosine similarity，[-1, 1]，"
                "通常落 [0, 1]）；NULL = 未计算 / 缺 reference / sidecar 不可达"
            ),
        ),
    )


def downgrade() -> None:
    """反向：drop 列。"""

    op.drop_column("shots", "consistency_score")
