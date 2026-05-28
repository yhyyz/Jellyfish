"""0017 - W27-T2 视觉一致性 status + retry 计数列。

W27-T1（alembic 0015）落了 ``shots.consistency_score``；W27-T2 在它之上
加两列把"分数"翻译成可被前端 / chapter_av_export pre-gate 直接消费的
**业务状态**：

- ``consistency_status`` (``VARCHAR(16)``，nullable)：``pass`` / ``warning`` /
  ``fail`` 三态。允许 ``NULL`` 表示从未跑过 :mod:`threshold_engine.evaluate`，
  与"跑过但 score 缺失"区分（后者由 ``threshold_engine.evaluate`` 显式判成
  ``warning``）。
- ``consistency_retry_count`` (``INTEGER NOT NULL DEFAULT 0``)：``threshold_engine``
  触发自动重生的次数计数；hard cap 为 2，由
  :data:`app.services.visual_consistency.threshold_engine.MAX_AUTO_REGEN_RETRY`
  保证。落库时 ``server_default="0"`` 让历史行升级后自动得到 0，无需脚本
  回填。

为什么不复用现有 ``shots.status``：
    - ``shots.status`` 只表示"信息提取确认状态"（pending / ready），见
      :mod:`AGENTS.md` 的"状态语义约定"；视觉一致性是一条独立维度，必须
      与提取流分开存储。

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-28
"""

# pylint: disable=invalid-name,no-member

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0017"
down_revision: Union[str, Sequence[str], None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """给 ``shots`` 表加 ``consistency_status`` + ``consistency_retry_count``。"""

    op.add_column(
        "shots",
        sa.Column(
            "consistency_status",
            sa.String(length=16),
            nullable=True,
            comment=(
                "DINOv2 一致性判定结果：pass / warning / fail（W27-T2）；"
                "NULL 表示尚未跑过 threshold_engine.evaluate"
            ),
        ),
    )
    op.add_column(
        "shots",
        sa.Column(
            "consistency_retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment=(
                "threshold_engine 触发自动重生的次数；hard cap=2 "
                "（MAX_AUTO_REGEN_RETRY），达到后即使分数仍低也不再重派"
            ),
        ),
    )


def downgrade() -> None:
    """反向 drop 两列。"""

    op.drop_column("shots", "consistency_retry_count")
    op.drop_column("shots", "consistency_status")
