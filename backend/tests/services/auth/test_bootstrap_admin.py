"""``app.services.auth.bootstrap_admin`` 单元测试（P5 W32-T4 引入）。

覆盖 3 个 case：
- 表为空时新建 admin（status=created）
- 表已有用户时跳过（status=skipped，不重复插入）
- 重复调用 bootstrap_admin 仍然只 1 个 admin（幂等）
"""

# pylint: disable=invalid-name

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.models.types import UserRole
from app.models.user import User
from app.services.auth.bootstrap_admin import bootstrap_admin


@pytest_asyncio.fixture()
async def session(tmp_path: Path) -> AsyncIterator[AsyncSession]:
    """提供一个临时 SQLite async session，已建好 users 表。"""
    db_path = tmp_path / "bootstrap_admin_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_local = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    import app.models  # noqa: F401  pylint: disable=unused-import

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_local() as db:
        yield db

    await engine.dispose()


@pytest.mark.asyncio
async def test_bootstrap_admin_creates_when_empty(session: AsyncSession) -> None:
    """users 表为空时应创建一个 admin 用户。"""
    result = await bootstrap_admin(session)
    assert result["status"] == "created"

    count = await session.scalar(select(func.count(User.id)))
    assert count == 1

    admin = (await session.execute(select(User))).scalar_one()
    assert admin.role == UserRole.ADMIN
    assert admin.is_active is True
    assert admin.username == "admin"
    assert admin.hashed_password.startswith("$argon2"), (
        "admin 密码应是 argon2 哈希，而非明文"
    )


@pytest.mark.asyncio
async def test_bootstrap_admin_skips_when_users_exist(
    session: AsyncSession,
) -> None:
    """已有任何用户行时，bootstrap_admin 应跳过且不再插入。"""
    seeded = User(
        username="alice",
        email="alice@example.com",
        hashed_password="$argon2$placeholder",
        role=UserRole.MEMBER,
        is_active=True,
    )
    session.add(seeded)
    await session.commit()

    result = await bootstrap_admin(session)
    assert result["status"] == "skipped"

    count = await session.scalar(select(func.count(User.id)))
    assert count == 1, "bootstrap_admin 不应在表非空时新建用户"


@pytest.mark.asyncio
async def test_bootstrap_admin_is_idempotent(session: AsyncSession) -> None:
    """连续调用 bootstrap_admin 仍然只会有一条 admin（幂等保障）。"""
    first = await bootstrap_admin(session)
    second = await bootstrap_admin(session)

    assert first["status"] == "created"
    assert second["status"] == "skipped"

    count = await session.scalar(select(func.count(User.id)))
    assert count == 1
