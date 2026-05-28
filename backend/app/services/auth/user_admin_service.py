"""User admin service 层（P5 W32-T10 引入）。

承担 ``/api/v1/settings/users`` admin CRUD 的业务逻辑：

- ``list_users``：分页 + 角色 / is_active 过滤
- ``create_user``：唯一性校验（username / email）+ 密码 argon2 哈希
- ``update_user``：可更新 email / role / is_active / password
- ``soft_delete_user``：软删除（is_active=False），admin 不能删除自己

W19b 双引擎事务边界：本 service 走 commit-then-flush；
密码哈希走 ``app.core.security.hash_password``，不直接 import pwdlib。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.types import UserRole
from app.models.user import User
from app.schemas.auth.user import UserCreate, UserUpdate


class UserConflictError(Exception):
    """username 或 email 与已有行冲突。"""


class UserNotFoundError(Exception):
    """目标 user_id 不存在。"""


class CannotDeleteSelfError(Exception):
    """admin 不允许删除自己（防止误把唯一 admin 删除导致系统失去 admin）。"""


async def list_users(
    db: AsyncSession,
    *,
    role: UserRole | None = None,
    is_active: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[User], int]:
    """分页 + 过滤列出用户。返回 ``(items, total)``。"""

    base = select(User)
    count_base = select(User)
    if role is not None:
        base = base.where(User.role == role)
        count_base = count_base.where(User.role == role)
    if is_active is not None:
        base = base.where(User.is_active == is_active)
        count_base = count_base.where(User.is_active == is_active)

    items_query = (
        base.order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await db.execute(items_query)).scalars().all())

    all_rows = list((await db.execute(count_base)).scalars().all())
    total = len(all_rows)

    return items, total


async def create_user(db: AsyncSession, payload: UserCreate) -> User:
    """admin 创建一条新 user 行。

    Raises:
        UserConflictError: username 或 email 已存在。
    """

    existing = await db.execute(
        select(User).where(
            (User.username == payload.username) | (User.email == payload.email)
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise UserConflictError(
            f"username '{payload.username}' or email '{payload.email}' already exists"
        )

    user = User(
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        is_active=payload.is_active,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise UserConflictError(str(exc)) from exc
    await db.refresh(user)
    return user


async def update_user(
    db: AsyncSession,
    *,
    user_id: str,
    payload: UserUpdate,
) -> User:
    """admin 更新指定 user 的可变字段。

    Raises:
        UserNotFoundError: user_id 不存在。
        UserConflictError: email 与已有行冲突。
    """

    user = await db.get(User, user_id)
    if user is None:
        raise UserNotFoundError(f"user {user_id} not found")

    if payload.email is not None and payload.email != user.email:
        dup = await db.execute(
            select(User).where(User.email == payload.email, User.id != user_id)
        )
        if dup.scalar_one_or_none() is not None:
            raise UserConflictError(f"email '{payload.email}' already exists")
        user.email = payload.email
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password is not None:
        user.hashed_password = hash_password(payload.password)

    await db.commit()
    await db.refresh(user)
    return user


async def soft_delete_user(
    db: AsyncSession,
    *,
    user_id: str,
    current_user_id: str,
) -> User:
    """软删除用户（is_active=False）；admin 不允许删除自己。

    Raises:
        CannotDeleteSelfError: 调用者尝试删除自己。
        UserNotFoundError: user_id 不存在。
    """

    if user_id == current_user_id:
        raise CannotDeleteSelfError("admin cannot soft-delete itself")

    user = await db.get(User, user_id)
    if user is None:
        raise UserNotFoundError(f"user {user_id} not found")

    user.is_active = False
    await db.commit()
    await db.refresh(user)
    return user
