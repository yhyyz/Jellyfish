"""0002 - 添加 Project.kind 列以支持剧情带货项目类型。

为 ``projects`` 表新增 ``kind`` 列，用于区分普通短剧（``drama``）与剧情
带货项目（``commerce_story``）。落库步骤：

1. 添加 ``kind VARCHAR(32)`` 列，先允许为空、设默认值 ``'drama'``，
   保证既有行可以平滑回填；
2. 显式回填所有历史行的 ``kind = 'drama'``；
3. 将列改为 ``NOT NULL``（保留 server_default ``'drama'`` 以兼容裸
   ``INSERT``）；
4. 在 ``kind`` 列上建立 ``ix_projects_kind`` 索引，用于按项目类型筛选。

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-25
"""

# pylint: disable=invalid-name,no-member

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """添加 ``projects.kind`` 列、回填默认值并建立索引。"""
    # 步骤 1：先以 nullable + server_default 形式新增列，确保历史行可被回填。
    op.add_column(
        "projects",
        sa.Column(
            "kind",
            sa.String(length=32),
            nullable=True,
            server_default="drama",
            comment="项目类型：drama=短剧；commerce_story=剧情带货",
        ),
    )

    # 步骤 2：显式回填，保证哪怕 server_default 在某些方言下未生效也有兜底值。
    op.execute("UPDATE projects SET kind='drama' WHERE kind IS NULL")

    # 步骤 3：收紧约束，列变为 NOT NULL；保留 server_default 兼容裸 INSERT。
    with op.batch_alter_table("projects") as batch_op:
        batch_op.alter_column(
            "kind",
            existing_type=sa.String(length=32),
            nullable=False,
            existing_server_default="drama",
            existing_comment="项目类型：drama=短剧；commerce_story=剧情带货",
        )

    # 步骤 4：建立筛选索引。
    op.create_index("ix_projects_kind", "projects", ["kind"])


def downgrade() -> None:
    """回滚：先删除索引，再删除 ``kind`` 列。"""
    op.drop_index("ix_projects_kind", table_name="projects")
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_column("kind")
