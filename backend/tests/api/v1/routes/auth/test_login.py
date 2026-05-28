"""Tests for ``/api/v1/login/access-token`` (P5 W32-T5)。

5 cases：
- happy path：admin 登录获取 JWT
- 用户不存在 → 401
- 密码错误 → 401
- is_active=False → 400
- 旧 bcrypt 哈希用户登录后 hashed_password 自动升级到 argon2
"""

# pylint: disable=invalid-name

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.models  # noqa: F401  pylint: disable=unused-import
from app.core.db import Base
from app.core.security import decode_access_token, hash_password
from app.dependencies import get_db
from app.main import app
from app.models.types import UserRole
from app.models.user import User


async def _build_engine() -> tuple[
    async_sessionmaker[AsyncSession], AsyncEngine
]:
    """构造 in-memory SQLite + sessionmaker，并建好全部表。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    sessionmaker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return sessionmaker, engine


def _make_override(sessionmaker: async_sessionmaker[AsyncSession]):
    """生成 ``get_db`` 依赖覆盖，使路由用本测试的 in-memory session。"""

    async def _get_db() -> AsyncGenerator[AsyncSession, None]:
        async with sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return _get_db


async def _seed_user(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    username: str = "alice",
    email: str = "alice@example.com",
    password: str = "alice-pass-12345",
    role: UserRole = UserRole.MEMBER,
    is_active: bool = True,
    use_bcrypt: bool = False,
) -> str:
    """种入一条 user 行，返回新建的 user.id。"""
    if use_bcrypt:
        bcrypt_only = PasswordHash((BcryptHasher(),))
        hashed = bcrypt_only.hash(password)
    else:
        hashed = hash_password(password)
    user = User(
        username=username,
        email=email,
        hashed_password=hashed,
        role=role,
        is_active=is_active,
    )
    async with sessionmaker() as db:
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user.id


@pytest.mark.asyncio
async def test_login_happy_path_returns_jwt(client: TestClient) -> None:
    """正确凭据登录应返回 200 + JWT，sub claim 等于 user.id。"""
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    try:
        user_id = await _seed_user(
            sessionmaker,
            username="alice",
            password="correct-pass",
            role=UserRole.MEMBER,
        )

        response = client.post(
            "/api/v1/login/access-token",
            data={"username": "alice", "password": "correct-pass"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["code"] == 200
        token_data = body["data"]
        assert token_data["token_type"] == "bearer"
        assert token_data["expires_in"] >= 60
        token = token_data["access_token"]
        assert decode_access_token(token) == user_id
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_login_unknown_user_returns_401(client: TestClient) -> None:
    """用户不存在应返回 401（与"密码错"消息一致避免用户枚举）。"""
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    try:
        response = client.post(
            "/api/v1/login/access-token",
            data={"username": "nobody", "password": "whatever"},
        )
        assert response.status_code == 401, response.text
        assert "Incorrect" in response.json()["message"]
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(client: TestClient) -> None:
    """密码错误应返回 401（与"用户不存在"消息一致避免用户枚举）。"""
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    try:
        await _seed_user(sessionmaker, password="right-pass")
        response = client.post(
            "/api/v1/login/access-token",
            data={"username": "alice", "password": "wrong-pass"},
        )
        assert response.status_code == 401, response.text
        assert "Incorrect" in response.json()["message"]
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_login_inactive_user_returns_400(client: TestClient) -> None:
    """is_active=False 应返回 400 ``Inactive user``。"""
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    try:
        await _seed_user(
            sessionmaker, password="alice-pass", is_active=False
        )
        response = client.post(
            "/api/v1/login/access-token",
            data={"username": "alice", "password": "alice-pass"},
        )
        assert response.status_code == 400, response.text
        assert "Inactive" in response.json()["message"]
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_login_upgrades_legacy_bcrypt_hash(client: TestClient) -> None:
    """旧 bcrypt 用户登录成功后 hashed_password 应自动升级到 argon2。"""
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    try:
        await _seed_user(
            sessionmaker, password="legacy-pass", use_bcrypt=True
        )

        async with sessionmaker() as db:
            row = (await db.execute(select(User))).scalar_one()
            assert row.hashed_password.startswith(
                ("$2a$", "$2b$")
            ), "种入的应是 bcrypt 哈希"

        response = client.post(
            "/api/v1/login/access-token",
            data={"username": "alice", "password": "legacy-pass"},
        )
        assert response.status_code == 200, response.text

        async with sessionmaker() as db:
            row = (await db.execute(select(User))).scalar_one()
            assert row.hashed_password.startswith("$argon2"), (
                "登录后 hashed_password 应升级到 argon2，"
                f"实际: {row.hashed_password[:20]}"
            )
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
