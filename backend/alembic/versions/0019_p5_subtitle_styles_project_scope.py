"""0019 - W30-T1 subtitle_styles 加 project_id FK 列。

P5 W30 在 ``subtitle_styles`` 表上扩 1 列 ``project_id``，把 P3 W18 仅有的
"系统级 seed"字幕样式目录扩成"系统级 + 项目级覆盖"双栈：

- ``project_id`` (``VARCHAR(64)``，nullable, FK ``projects.id`` ON DELETE CASCADE)：
  项目级覆盖样式归属的项目 ID。``NULL`` 表示系统级（DOUYIN_DEFAULT 等
  W18 内置 seed），非 ``NULL`` 表示某个项目自定义的覆盖样式。

为什么 ``nullable=True`` + 不加 backfill：
    系统级行（``is_system=TRUE``）保持 ``project_id=NULL`` 不变；项目级
    行才填具体 project ID。``upgrade`` 后存量数据自动 fallback 到 NULL，
    历史读路径（``GET /api/v1/commerce/subtitle-styles?is_system=true``）
    与 W18 ``shot_subtitle_render_worker`` 行为完全不变。

为什么不加 ``UNIQUE (project_id, name)``：
    MySQL 不支持 partial index，``UNIQUE (project_id, name)`` 在
    ``project_id IS NULL`` 行间会把多个系统级行（不同 name）误认为可冲突；
    生成列 + UNIQUE 的方案跨 SQLite / MySQL 兼容性差。决策 D-P5-2 选择
    在 service 层做 ``(project_id, name)`` 唯一性校验，DB 仅加普通索引。

为什么 ``add_column`` 走 ``batch_alter_table``：
    SQLite 不支持 ``ALTER TABLE ADD CONSTRAINT``，纯 ``op.add_column`` 加
    带 FK 的列会抛 ``NotImplementedError``；与 0009 / 0011 多次 FK 扩列做
    法保持一致，使用 ``batch_alter_table`` 复制重建表，跨 SQLite / MySQL /
    PostgreSQL 兼容。

幂等保障：
    ``project_id`` ``nullable=True``，不需要业务侧默认值；``upgrade`` 后无
    backfill，``downgrade`` 直接 ``drop_column`` 即可。

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-28
"""

# pylint: disable=invalid-name,no-member

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0019"
down_revision: Union[str, Sequence[str], None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """在 ``subtitle_styles`` 上加 ``project_id`` FK 列与同名索引。"""

    with op.batch_alter_table("subtitle_styles") as batch:
        batch.add_column(
            sa.Column(
                "project_id",
                sa.String(length=64),
                sa.ForeignKey(
                    "projects.id",
                    name="fk_subtitle_styles_project_id",
                    ondelete="CASCADE",
                ),
                nullable=True,
                comment=(
                    "项目级覆盖样式归属的项目 ID；NULL=系统级 seed，"
                    "非 NULL=该项目自定义覆盖；ON DELETE CASCADE 随项目删除"
                ),
            ),
        )

    op.create_index(
        "ix_subtitle_styles_project_id",
        "subtitle_styles",
        ["project_id"],
        unique=False,
    )


def downgrade() -> None:
    """反向 drop ``project_id`` 列与索引。"""

    op.drop_index(
        "ix_subtitle_styles_project_id", table_name="subtitle_styles"
    )
    with op.batch_alter_table("subtitle_styles") as batch:
        batch.drop_column("project_id")
