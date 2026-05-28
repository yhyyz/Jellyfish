"""Tests for ``/api/v1/settings/api-keys`` admin endpoints (P4 W24-T1).

These cover the admin-side CRUD surface of the per-key quota
service. The middleware-level bcrypt verification is exercised
in ``tests/core/test_api_key_auth.py``; this module focuses on
the HTTP contract:

- ``POST /api/v1/settings/api-keys`` creates a key and returns
  the **plaintext exactly once** in the response body;
- ``GET /api/v1/settings/api-keys`` excludes revoked keys by
  default and never echoes plaintext;
- ``POST /api/v1/settings/api-keys/revoke`` flips ``is_active``
  to ``False`` and the row vanishes from the default list.
"""

# pylint: disable=invalid-name

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.models  # noqa: F401  pylint: disable=unused-import

from app.core.db import Base
from app.dependencies import get_current_user, get_db, require_admin
from app.main import app
from app.models.types import UserRole
from app.models.user import User


def _bypass_admin_dep() -> User:
    """覆盖 ``require_admin`` 依赖，让 pre-existing 测试无需 mint JWT。

    P5 W32-T7 在 ``/api/v1/settings/api-keys`` 路由层加了 ``require_admin``
    守卫；本测试模块聚焦 CRUD 契约本身（plaintext 仅本次返回 / 列表过滤等),
    不重复测 RBAC（那些用例放在 ``tests/api/v1/test_admin_endpoints_rbac.py``）,
    因此在 dependency_overrides 里把守卫替换成虚拟 admin user。
    """

    return User(
        id="__test_admin__",
        username="__test_admin__",
        email="test-admin@jellyfish.local",
        hashed_password="",
        role=UserRole.ADMIN,
        is_active=True,
    )


def _install_auth_overrides() -> None:
    """同时覆盖 ``get_current_user`` 与 ``require_admin``，确保子依赖也走假 user。"""
    app.dependency_overrides[get_current_user] = _bypass_admin_dep
    app.dependency_overrides[require_admin] = _bypass_admin_dep


async def _build_engine() -> tuple[
    async_sessionmaker[AsyncSession], AsyncEngine
]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return sessionmaker, engine


def _make_override(sessionmaker: async_sessionmaker[AsyncSession]):
    async def _get_db() -> AsyncGenerator[AsyncSession, None]:
        async with sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:  # noqa: BLE001
                await session.rollback()
                raise

    return _get_db


# ---------------------------------------------------------------------------
# 1) create returns 201 and plaintext appears once in response only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_api_key_returns_plaintext_in_response_only(
    client: TestClient,
) -> None:
    """``POST /settings/api-keys`` returns the plaintext key once.

    Subsequent ``GET`` calls must never expose plaintext —
    the only place it can ever surface is the create response.
    """
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    _install_auth_overrides()
    try:
        response = client.post(
            "/api/v1/settings/api-keys",
            json={
                "description": "partner-acme",
                "daily_limit": 200,
                "monthly_limit": 5000,
                "rate_per_minute": 30,
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["code"] == 201
        data = body["data"]
        plaintext = data["plaintext_key"]
        assert plaintext.startswith("jellyfish_")
        assert data["description"] == "partner-acme"
        assert data["daily_limit"] == 200
        assert data["api_key_hash"].startswith("$2b$")
        assert plaintext not in data["api_key_hash"]

        # GET list does NOT contain plaintext
        list_resp = client.get("/api/v1/settings/api-keys")
        assert list_resp.status_code == 200, list_resp.text
        for item in list_resp.json()["data"]:
            assert "plaintext_key" not in item
            assert plaintext not in str(item)
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


# ---------------------------------------------------------------------------
# 2) list excludes revoked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_api_keys_excludes_revoked_by_default(
    client: TestClient,
) -> None:
    """List endpoint defaults to active-only; revoked keys disappear."""
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    _install_auth_overrides()
    try:
        # Seed two keys.
        first = client.post(
            "/api/v1/settings/api-keys",
            json={"description": "alive", "daily_limit": 10},
        )
        assert first.status_code == 201, first.text
        second = client.post(
            "/api/v1/settings/api-keys",
            json={"description": "to-revoke", "daily_limit": 10},
        )
        assert second.status_code == 201, second.text
        revoked_hash = second.json()["data"]["api_key_hash"]

        # Revoke second.
        revoke_resp = client.post(
            "/api/v1/settings/api-keys/revoke",
            json={"api_key_hash": revoked_hash},
        )
        assert revoke_resp.status_code == 200, revoke_resp.text
        assert revoke_resp.json()["data"]["is_active"] is False

        # Default list: only the surviving one.
        active_list = client.get("/api/v1/settings/api-keys")
        assert active_list.status_code == 200
        descriptions = {item["description"] for item in active_list.json()["data"]}
        assert descriptions == {"alive"}

        # include_inactive=true → both surface.
        full_list = client.get(
            "/api/v1/settings/api-keys", params={"include_inactive": True}
        )
        assert full_list.status_code == 200
        descriptions_all = {item["description"] for item in full_list.json()["data"]}
        assert descriptions_all == {"alive", "to-revoke"}
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


# ---------------------------------------------------------------------------
# 3) revoke unknown hash returns 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_unknown_hash_returns_404(client: TestClient) -> None:
    """Revoking a hash that does not exist returns 404, not 200."""
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    _install_auth_overrides()
    try:
        response = client.post(
            "/api/v1/settings/api-keys/revoke",
            json={"api_key_hash": "$2b$12$does_not_exist"},
        )
        assert response.status_code == 404, response.text
        body = response.json()
        assert body["code"] == 404
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Bonus: usage endpoint returns counters by hash.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_usage_endpoint_returns_counters(client: TestClient) -> None:
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    _install_auth_overrides()
    try:
        created = client.post(
            "/api/v1/settings/api-keys",
            json={"description": "u", "daily_limit": 7},
        )
        api_key_hash = created.json()["data"]["api_key_hash"]
        usage = client.post(
            "/api/v1/settings/api-keys/usage",
            json={"api_key_hash": api_key_hash},
        )
        assert usage.status_code == 200, usage.text
        body = usage.json()["data"]
        assert body["api_key_hash"] == api_key_hash
        assert body["daily_limit"] == 7
        assert body["consumed_today"] == 0
        assert body["is_active"] is True
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
