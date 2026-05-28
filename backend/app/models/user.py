"""用户 ORM 模型（P5 W32-T1 引入）。

承载 RBAC 用户体系的第一张表 ``users``，与 alembic 0021 schema 一一对应。

设计要点（与决策 D-P5-3 保持一致）：

- ``id`` 用 UUID hex string（``uuid.uuid4().hex``，36 位无连字符），
  与项目内 ``files.id`` / ``voice_packs.id`` 等表的主键风格一致；
- ``role`` 列底层是 ``VARCHAR(16)``，ORM 端用 :class:`UserRole` enum 做类型守卫；
  新增角色时只需要在枚举里加值，不需要 ALTER TYPE；
- ``hashed_password`` 永远只存 argon2 哈希（由 ``app.core.security.hash_password``
  生成），鉴权失败时统一返回模糊错误，避免用户枚举攻击；
- ``is_active`` 软禁用：``False`` 时 ``get_current_user`` 直接 403；
  也用作 admin 列表上的可视化 toggle，便于运营临时停用账号；
- 时间戳字段双轨：列默认 server_default=now()，ORM 端再用
  ``default=lambda: datetime.now(timezone.utc)`` 兜底，兼容
  alembic 升迁后 INSERT 路径与单元测试 in-memory SQLite。

JWT claims 与 role 关系（重要约束）：
    JWT 里只放 ``sub=user.id``，**绝不**放 ``role`` claim。原因是用户被降
    权后旧 token 仍 admin 会出严重安全事故；``get_current_user`` 在每个
    请求里都 ``session.get(User, user_id)`` 实时拉 role，identity map
    O(1) 命中无性能负担。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.types import UserRole


class User(Base):
    """用户表（P5 W32-T1 引入）。

    业务约定：

    - ``id`` 用 ``uuid.uuid4().hex`` 生成，36 位字符串主键，跨数据源/导出友好。
    - 新建用户默认 ``role=MEMBER``；首次启动期由 ``bootstrap_admin`` 用
      ``BOOTSTRAP_ADMIN_USERNAME`` / ``BOOTSTRAP_ADMIN_PASSWORD`` 创建一个
      ``ADMIN`` 用户（仅当 ``users`` 表为空）。
    - ``hashed_password`` 用 ``pwdlib`` argon2 哈希生成；登录路径会通过
      ``verify_and_update`` 把旧 bcrypt 哈希自动升级到 argon2。
    - ``is_active`` 软禁用；删除用户走 ``DELETE`` 把 ``is_active=False``，
      DB 行保留作审计；admin 不允许删除自己（service 层校验）。
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: uuid.uuid4().hex,
    )
    username: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    role: Mapped[UserRole] = mapped_column(
        SAEnum(
            UserRole,
            native_enum=False,
            length=16,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=UserRole.MEMBER,
        index=True,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover - 仅调试展示
        return (
            f"<User id={self.id!r} username={self.username!r} "
            f"role={self.role.value!r} is_active={self.is_active}>"
        )
