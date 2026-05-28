"""Tests for ``GET /api/v1/users/me`` (P5 W32-followup)。

5 cases：
- admin JWT token → 200 + role=admin + 不暴露 hashed_password
- member JWT token → 200 + role=member
- Stage-1 静态 fallback (Bearer settings.api_key) → 200 + id=__static_fallback__ + role=admin
- 无 Authorization 头 → 401
- 过期 JWT → 401
"""

# pylint: disable=invalid-name

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.models  # noqa: F401  pylint: disable=unused-import
from app.config import settings
from app.core.db import Base
from app.core.security import create_access_token, hash_password
from app.dependencies import get_db
from app.main import app
from app.models.types import UserRole
from app.models.user import User


async def _build_engine() -> tuple[
    async_sessionmaker[AsyncSession], AsyncEngine
]:
    """构造内存 SQLite 引擎 + sessionmaker，并在其中建表。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    sessionmaker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return sessionmaker, engine


def _make_override(sessionmaker: async_sessionmaker[AsyncSession]):
    """生成 FastAPI ``get_db`` override，把请求路由到测试用 sessionmaker。"""

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
    username: str,
    role: UserRole,
    is_active: bool = True,
) -> tuple[str, str]:
    """种入一个用户，返回 (user_id, jwt_token)。"""
    user = User(
        username=username,
        email=f"{username}@example.com",
        hashed_password=hash_password(f"{username}-pw"),
        role=role,
        is_active=is_active,
    )
    async with sessionmaker() as db:
        db.add(user)
        await db.commit()
        await db.refresh(user)
    token = create_access_token(user.id)
    return user.id, token


@pytest.mark.asyncio
async def test_read_users_me_with_admin_token_returns_admin_user(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """admin JWT → 200，返回 role=admin，且不暴露 hashed_password。"""
    monkeypatch.setattr(settings, "jwt_fallback_to_static", False)
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    try:
        admin_id, token = await _seed_user(
            sessionmaker, username="admin_me", role=UserRole.ADMIN
        )
        resp = client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 200
        data = body["data"]
        assert data["id"] == admin_id
        assert data["username"] == "admin_me"
        assert data["role"] == "admin"
        assert data["is_active"] is True
        assert "hashed_password" not in data
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_read_users_me_with_member_token_returns_member_user(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """member JWT → 200，返回 role=member（关键 bug 修复证据）。"""
    monkeypatch.setattr(settings, "jwt_fallback_to_static", False)
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    try:
        member_id, token = await _seed_user(
            sessionmaker, username="bob_me", role=UserRole.MEMBER
        )
        resp = client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["id"] == member_id
        assert data["username"] == "bob_me"
        assert data["role"] == "member"
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_read_users_me_with_static_fallback_returns_static_admin(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``jwt_fallback_to_static=True`` + Bearer ``settings.api_key`` →
    200，返回 ``id=__static_fallback__`` + role=admin。"""
    monkeypatch.setattr(settings, "jwt_fallback_to_static", True)
    monkeypatch.setattr(settings, "api_key", "sk-fallback-test-key")
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    try:
        # 两个头都必传：``X-API-Key`` 让 :class:`ApiKeyMiddleware` 放行，
        # ``Authorization: Bearer <api_key>`` 让 :func:`get_current_user`
        # 命中 Stage-1 静态 fallback 分支。
        resp = client.get(
            "/api/v1/users/me",
            headers={
                "X-API-Key": "sk-fallback-test-key",
                "Authorization": "Bearer sk-fallback-test-key",
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["id"] == "__static_fallback__"
        assert data["username"] == "__static_admin__"
        assert data["role"] == "admin"
        assert data["is_active"] is True
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_read_users_me_without_token_returns_401(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """无 Authorization 头 → 401。"""
    monkeypatch.setattr(settings, "jwt_fallback_to_static", False)
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    try:
        resp = client.get("/api/v1/users/me")
        assert resp.status_code == 401, resp.text
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_read_users_me_with_expired_token_returns_401(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """过期 JWT → 401。"""
    monkeypatch.setattr(settings, "jwt_fallback_to_static", False)
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    try:
        # 已知 user，但用过期 token（expires_delta 为负数）。
        user = User(
            username="stale",
            email="stale@example.com",
            hashed_password=hash_password("pw"),
            role=UserRole.ADMIN,
            is_active=True,
        )
        async with sessionmaker() as db:
            db.add(user)
            await db.commit()
            await db.refresh(user)
        expired_token = create_access_token(
            user.id, expires_delta=timedelta(seconds=-60)
        )
        resp = client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert resp.status_code == 401, resp.text
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
