"""User service 层（P5 W32-T5 引入）。

承担 ``users`` 表的业务读写：

- ``get_user_by_username``：登录路径的用户查找；
- ``authenticate_user``：核对密码 + 自动升级旧 bcrypt 哈希；

严格遵守 AGENTS.md §4 分层契约：
- 路由层只调本 service，不直接 import jwt / pwdlib；
- 本 service 不组织响应壳，错误以异常形式抛出由路由翻成 HTTP。
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_password
from app.models.user import User


logger = logging.getLogger(__name__)


async def get_user_by_username(
    db: AsyncSession, username: str
) -> User | None:
    """按 username 查询用户，找不到返回 ``None``。"""
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def authenticate_user(
    db: AsyncSession,
    username: str,
    password: str,
) -> User | None:
    """校验用户名 + 密码，返回 ``User`` 实例或 ``None``（用户不存在或密码错误）。

    自动升级旧 bcrypt 哈希到 argon2：
        当 :func:`app.core.security.verify_password` 返回 ``new_hash`` 非空时，
        说明 DB 里存的是旧 bcrypt 格式。本函数把新的 argon2 哈希写回，
        在 ``commit`` 前完成升级，下次登录就走 argon2 verify。

    返回 ``None`` 的两种情况合并处理：用户不存在 / 密码错误。路由层应
    返回相同的 401 错误消息（"Incorrect username or password"），避免
    用户枚举攻击。
    """

    user = await get_user_by_username(db, username)
    if user is None:
        return None

    ok, new_hash = verify_password(password, user.hashed_password)
    if not ok:
        return None

    if new_hash is not None:
        logger.info(
            "user '%s' password hash auto-upgraded from legacy to argon2",
            user.username,
        )
        user.hashed_password = new_hash
        await db.commit()

    return user
