"""Tests for ``/api/v1/settings/users`` admin CRUD (P5 W32-T10)。

8 cases：
- list 返回 paginated
- create happy path 201
- create 同 username 409
- update role / password
- update is_active
- delete 软删除 → is_active=False
- admin 不能删自己 400
- member token 调用 → 403
"""

# pylint: disable=invalid-name

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
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
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    sessionmaker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return sessionmaker, engine


def _make_override(sessionmaker: async_sessionmaker[AsyncSession]):
    async def _get_db() -> AsyncGenerator[AsyncSession, None]:
        async with sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return _get_db


async def _seed_admin(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> tuple[str, str]:
    """种入 admin user，返回 (admin_id, admin_token)。"""
    user = User(
        username="admin",
        email="admin@example.com",
        hashed_password=hash_password("admin-pw"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    async with sessionmaker() as db:
        db.add(user)
        await db.commit()
        await db.refresh(user)
    token = create_access_token(user.id)
    return user.id, token


async def _seed_member(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> tuple[str, str]:
    """种入 member user，返回 (id, token)。"""
    user = User(
        username="bob",
        email="bob@example.com",
        hashed_password=hash_password("bob-pw"),
        role=UserRole.MEMBER,
        is_active=True,
    )
    async with sessionmaker() as db:
        db.add(user)
        await db.commit()
        await db.refresh(user)
    token = create_access_token(user.id)
    return user.id, token


@pytest.mark.asyncio
async def test_list_users_returns_paginated(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """admin 列表请求应返回 paginated data。"""
    monkeypatch.setattr(settings, "jwt_fallback_to_static", False)
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    try:
        _, token = await _seed_admin(sessionmaker)
        resp = client.get(
            "/api/v1/settings/users",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 200
        assert body["data"]["items"][0]["username"] == "admin"
        assert body["data"]["pagination"]["total"] == 1
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_user_happy_path(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """admin 创建用户应 201 + 不返回 hashed_password。"""
    monkeypatch.setattr(settings, "jwt_fallback_to_static", False)
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    try:
        _, token = await _seed_admin(sessionmaker)
        resp = client.post(
            "/api/v1/settings/users",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "username": "alice",
                "email": "alice@example.com",
                "password": "alicepw123",
                "role": "member",
            },
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert data["username"] == "alice"
        assert data["role"] == "member"
        assert "hashed_password" not in data
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_user_duplicate_username_returns_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """username 重复 → 409 Conflict。"""
    monkeypatch.setattr(settings, "jwt_fallback_to_static", False)
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    try:
        _, token = await _seed_admin(sessionmaker)
        resp = client.post(
            "/api/v1/settings/users",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "username": "admin",
                "email": "another@example.com",
                "password": "pwpwpw12",
            },
        )
        assert resp.status_code == 409, resp.text
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_update_user_role_and_password(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PATCH 改 role + password；新密码可登录。"""
    monkeypatch.setattr(settings, "jwt_fallback_to_static", False)
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    try:
        _, admin_token = await _seed_admin(sessionmaker)
        member_id, _ = await _seed_member(sessionmaker)

        resp = client.patch(
            f"/api/v1/settings/users/{member_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"role": "admin", "password": "newer-pw-456"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["role"] == "admin"

        async with sessionmaker() as db:
            row = (
                await db.execute(select(User).where(User.id == member_id))
            ).scalar_one()
            assert row.role == UserRole.ADMIN
            assert row.hashed_password.startswith("$argon2")
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_update_user_is_active_toggle(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PATCH is_active=false 应禁用，再 PATCH true 重启用。"""
    monkeypatch.setattr(settings, "jwt_fallback_to_static", False)
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    try:
        _, admin_token = await _seed_admin(sessionmaker)
        member_id, _ = await _seed_member(sessionmaker)

        resp = client.patch(
            f"/api/v1/settings/users/{member_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"is_active": False},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["is_active"] is False

        resp2 = client.patch(
            f"/api/v1/settings/users/{member_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"is_active": True},
        )
        assert resp2.status_code == 200
        assert resp2.json()["data"]["is_active"] is True
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_soft_delete_user(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DELETE 应软删（is_active=False，行保留）。"""
    monkeypatch.setattr(settings, "jwt_fallback_to_static", False)
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    try:
        _, admin_token = await _seed_admin(sessionmaker)
        member_id, _ = await _seed_member(sessionmaker)

        resp = client.delete(
            f"/api/v1/settings/users/{member_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200, resp.text

        async with sessionmaker() as db:
            row = (
                await db.execute(select(User).where(User.id == member_id))
            ).scalar_one()
            assert row.is_active is False
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_admin_cannot_delete_self_returns_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """admin 不能删除自己 → 400。"""
    monkeypatch.setattr(settings, "jwt_fallback_to_static", False)
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    try:
        admin_id, admin_token = await _seed_admin(sessionmaker)
        resp = client.delete(
            f"/api/v1/settings/users/{admin_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 400, resp.text
        assert "cannot" in resp.json()["message"].lower()
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_member_token_returns_403(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """member token 调用 admin endpoint → 403。"""
    monkeypatch.setattr(settings, "jwt_fallback_to_static", False)
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    try:
        _, member_token = await _seed_member(sessionmaker)
        resp = client.get(
            "/api/v1/settings/users",
            headers={"Authorization": f"Bearer {member_token}"},
        )
        assert resp.status_code == 403, resp.text
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
