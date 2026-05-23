"""baseline — 标记当前数据库 schema 已存在。

这是 Alembic 的初始 stamp 迁移。数据库表已由 init_db.py 创建，
此 revision 仅在 alembic_version 表中记录起点版本号。
后续新增的 schema 变更通过 Alembic 管理。

Revision ID: 0001
Revises:
Create Date: 2026-05-23 02:16:22.378343

"""

from typing import Sequence, Union

from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401


revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """空操作 — schema 已由 init_db.py / SQL 文件创建。"""
    pass


def downgrade() -> None:
    """不支持回退到 baseline 之前。"""
    pass
