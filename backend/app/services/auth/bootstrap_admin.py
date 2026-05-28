"""启动期 ``bootstrap_admin`` 幂等创建首个 admin 用户（P5 W32-T4 引入）。

调用入口：``app.main.lifespan`` 在 ``bootstrap_async_state`` 之后调用。

幂等语义：
    - 仅当 ``users`` 表为空（``COUNT(*) == 0``）时创建一条 admin 用户。
    - 当表中已有任何用户行（无论是否 admin）时直接跳过，避免覆盖已有
      管理员或在每次启动时重复插入。

凭据来源：
    - ``settings.bootstrap_admin_username`` / ``email`` / ``password``
      由 ``.env`` 注入。
    - 默认值 ``admin / admin@jellyfish.local / changeme`` 仅供开发期使用，
      生产部署必须在 ``.env`` 中改写（见 ``app.config`` 的注释）。

事务边界（W19b 双引擎契约）：
    - 函数自身不调用 ``session.commit()``，由 lifespan 调用方负责事务边界。
    - 但因为本函数属于"启动期一次性写入"，不归属任何 HTTP 请求生命周期，
      所以走显式 commit 不会与 W19b 业务路径的 commit-then-flush 冲突。

返回结构：
    ``{"status": "created" | "skipped"}``，便于启动日志打印与单测断言。
"""

from __future__ import annotations

import logging
from typing import Literal, TypedDict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import hash_password
from app.models.types import UserRole
from app.models.user import User


logger = logging.getLogger(__name__)


class BootstrapAdminResult(TypedDict):
    """``bootstrap_admin`` 返回结构：仅含 status 字段，便于日志与断言。"""

    status: Literal["created", "skipped"]


async def bootstrap_admin(db: AsyncSession) -> BootstrapAdminResult:
    """启动期幂等创建首个 admin 用户。

    Args:
        db: 来自 ``async_session_maker()`` 的 async session（lifespan 内）。

    Returns:
        ``{"status": "created"}`` 表示本次新建了 admin；``"skipped"`` 表示
        已有用户行，跳过创建。
    """

    count = await db.scalar(select(func.count(User.id)))
    if count and count > 0:
        logger.info(
            "bootstrap_admin: skipped, users table already has %s row(s)",
            count,
        )
        return {"status": "skipped"}

    admin = User(
        username=settings.bootstrap_admin_username,
        email=settings.bootstrap_admin_email,
        hashed_password=hash_password(settings.bootstrap_admin_password),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(admin)
    await db.commit()
    logger.warning(
        "bootstrap_admin: created admin user '%s' (change BOOTSTRAP_ADMIN_PASSWORD in production!)",
        admin.username,
    )
    return {"status": "created"}
