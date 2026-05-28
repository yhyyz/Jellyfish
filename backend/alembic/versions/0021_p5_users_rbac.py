"""0021 - W32-T1 引入 ``users`` 表（RBAC 用户体系基础设施）。

P5 W32 把 P1 起的"静态单 API key 守门"升级到完整的 JWT + RBAC 体系。
本迁移落第一张专属表 ``users``，承担：

- 登录鉴权（``username`` / ``hashed_password``，argon2 哈希存储）
- 角色访问控制（``role`` 字段，配合 :class:`app.models.types.UserRole`）
- 软禁用 / 启用（``is_active``）
- 标准创建/更新时间戳（``created_at`` / ``updated_at``）

为什么 ``id`` 用 ``CHAR(36)`` UUID 而非 ``BIGINT AUTOINCREMENT``：
    与项目内既有 ``files.id`` / ``voice_packs.id`` 等表保持一致风格——
    application 侧用 ``uuid.uuid4().hex`` 生成主键，跨数据源/导出友好。

为什么 ``role`` 用 ``VARCHAR(16)`` 而非 ``ENUM``（D-P5-3）：
    决策 D-P5-3 选择把 ``UserRole`` 放在 application 层（Python ``Enum``，
    SQLAlchemy ``Enum(native_enum=False)``），DB 层只用 ``VARCHAR(16)``。
    后续新增角色（如 ``editor`` / ``reviewer`` / ``billing``）不需要 ALTER
    TYPE，迁移成本极低。索引开销可忽略——当前 admin / member / viewer 三种
    取值集合远小于 16B。

为什么 ``username`` 与 ``email`` 都加 ``UNIQUE``：
    ``username`` 是登录入口，必须唯一；``email`` 是 P5 W32 收口的唯一联系
    渠道（之前 W26 ``escalation_owner_email`` 仅靠环境变量 fallback），
    后续 W33 / W34 邀请流程也以 ``email`` 作为收件人去重 key。

为什么不引入 ``Role`` / ``Permission`` 多对多表：
    YAGNI——当前只有 admin / member / viewer 三种角色，每条 API 的访问要求
    可以静态写在 router 装饰器里。真要做 fine-grained 权限再扩 ``permissions``
    表与 ``role_permissions`` 关联表，无需重构 ``users``。

幂等保障：
    ``upgrade`` 直接 ``op.create_table`` + 索引，不需要数据回填；
    ``downgrade`` 直接 ``op.drop_table``，不会牵连其它表（第一张落地表）。

Revision ID: 0021
Revises: 0020
Create Date: 2026-05-28
"""

# pylint: disable=invalid-name,no-member

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0021"
down_revision: Union[str, Sequence[str], None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新建 ``users`` 表 + 4 个索引（username / email / role / is_active）。"""

    op.create_table(
        "users",
        sa.Column(
            "id",
            sa.String(length=36),
            primary_key=True,
            comment="UUID hex string；application 层 uuid.uuid4().hex 生成",
        ),
        sa.Column(
            "username",
            sa.String(length=64),
            nullable=False,
            comment="登录用用户名，全局唯一",
        ),
        sa.Column(
            "email",
            sa.String(length=255),
            nullable=False,
            comment="邮箱，全局唯一；后续邀请流程以此去重",
        ),
        sa.Column(
            "hashed_password",
            sa.String(length=255),
            nullable=False,
            comment="argon2 哈希结果（含 salt + 参数前缀）；不存明文",
        ),
        sa.Column(
            "role",
            sa.String(length=16),
            nullable=False,
            server_default="member",
            comment=(
                "角色：admin / member / viewer；DB 层用 VARCHAR(16) 而非 ENUM，"
                "对应 app.models.types.UserRole；新增角色不需要 ALTER TYPE"
            ),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
            comment="软禁用开关；False 时 get_current_user 直接 403",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="创建时间（带时区）",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="更新时间；onupdate 由 ORM 端处理",
        ),
    )

    op.create_index(
        "ix_users_username",
        "users",
        ["username"],
        unique=True,
    )
    op.create_index(
        "ix_users_email",
        "users",
        ["email"],
        unique=True,
    )
    op.create_index(
        "ix_users_role",
        "users",
        ["role"],
        unique=False,
    )
    op.create_index(
        "ix_users_is_active",
        "users",
        ["is_active"],
        unique=False,
    )


def downgrade() -> None:
    """反向 drop ``users`` 表与四个索引。"""

    op.drop_index("ix_users_is_active", table_name="users")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
