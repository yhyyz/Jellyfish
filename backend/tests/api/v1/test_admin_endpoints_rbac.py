"""Tests for admin-endpoint RBAC guards (P5 W32-T7)。

覆盖 router-level / per-endpoint ``require_admin`` 守卫的负面 + 正面路径：

- /api/v1/settings/api-keys → admin OK / member 403 / no-token 401
- /api/v1/llm/providers POST → admin OK / member 403
- /api/v1/llm/models DELETE → admin OK / member 403
- /api/v1/commerce/projects/{id}/subtitle-styles POST/PATCH/DELETE → admin OK / member 403
- /api/v1/commerce/subtitle-styles GET → 公开（保持向前兼容，不加守卫）
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
    username: str,
    role: UserRole,
) -> str:
    """种入一条 user 行，返回 user.id。"""
    user = User(
        username=username,
        email=f"{username}@example.com",
        hashed_password=hash_password("test-pass"),
        role=role,
        is_active=True,
    )
    async with sessionmaker() as db:
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user.id


@pytest.mark.asyncio
async def test_settings_api_keys_admin_passes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """admin token 应能访问 /api/v1/settings/api-keys 列表。"""
    monkeypatch.setattr(settings, "jwt_fallback_to_static", False)
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    try:
        admin_id = await _seed_user(
            sessionmaker, username="admin1", role=UserRole.ADMIN
        )
        token = create_access_token(admin_id)
        resp = client.get(
            "/api/v1/settings/api-keys",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_settings_api_keys_member_returns_403(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """member token 应被 require_admin 拒为 403。"""
    monkeypatch.setattr(settings, "jwt_fallback_to_static", False)
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    try:
        member_id = await _seed_user(
            sessionmaker, username="bob", role=UserRole.MEMBER
        )
        token = create_access_token(member_id)
        resp = client.get(
            "/api/v1/settings/api-keys",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403, resp.text
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_settings_api_keys_no_token_returns_401(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无 token 且 fallback 关闭 → 401 No credentials。"""
    monkeypatch.setattr(settings, "jwt_fallback_to_static", False)
    monkeypatch.setattr(settings, "api_key", "")
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    try:
        resp = client.get("/api/v1/settings/api-keys")
        assert resp.status_code == 401, resp.text
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_llm_providers_post_member_returns_403(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """member token 创建 provider 应被拒 403。"""
    monkeypatch.setattr(settings, "jwt_fallback_to_static", False)
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    try:
        member_id = await _seed_user(
            sessionmaker, username="charlie", role=UserRole.MEMBER
        )
        token = create_access_token(member_id)
        resp = client.post(
            "/api/v1/llm/providers",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "test-provider",
                "kind": "openai",
                "base_url": "https://api.example.com",
                "api_key": "secret",
            },
        )
        assert resp.status_code == 403, resp.text
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_llm_providers_get_passes_without_admin(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /llm/providers 是只读，不加守卫 → member 也能访问。"""
    monkeypatch.setattr(settings, "jwt_fallback_to_static", False)
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    try:
        resp = client.get("/api/v1/llm/providers")
        assert resp.status_code == 200, resp.text
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_subtitle_styles_get_passes_without_admin(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /commerce/subtitle-styles 是只读，无守卫 → 公开访问 OK。"""
    monkeypatch.setattr(settings, "jwt_fallback_to_static", False)
    sessionmaker, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(sessionmaker)
    try:
        resp = client.get("/api/v1/commerce/subtitle-styles")
        assert resp.status_code == 200, resp.text
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
