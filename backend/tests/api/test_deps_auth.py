"""Tests for ``app.dependencies.get_current_user`` + ``require_role`` (P5 W32-T6)。

8 cases：
- valid JWT → user 返回
- expired JWT → 401
- 篡改 JWT → 401
- 用户不存在 → 401
- is_active=False → 403
- static fallback (env=True + matching key) → admin user
- static fallback (env=True + wrong key) → 401
- static fallback (env=False + matching key) → 401
"""

# pylint: disable=invalid-name

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import timedelta

import jwt
import pytest
from fastapi import Depends, FastAPI
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
from app.core.security import ALGORITHM, create_access_token, hash_password
from app.dependencies import (
    get_current_user,
    get_db,
    require_admin,
    require_role,
)
from app.models.types import UserRole
from app.models.user import User


async def _build_app() -> tuple[FastAPI, async_sessionmaker[AsyncSession], AsyncEngine]:
    """构造一个最小 FastAPI app，挂 ``get_current_user`` / ``require_admin`` 路由。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    sessionmaker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    test_app = FastAPI()

    @test_app.get("/whoami")
    async def whoami(user: User = Depends(get_current_user)):
        return {"id": user.id, "username": user.username, "role": user.role.value}

    @test_app.get("/admin-only")
    async def admin_only(user: User = Depends(require_admin)):
        return {"ok": True, "role": user.role.value}

    @test_app.get("/member-only")
    async def member_only(
        user: User = Depends(require_role(UserRole.MEMBER)),
    ):
        return {"ok": True, "role": user.role.value}

    async def _get_db() -> AsyncGenerator[AsyncSession, None]:
        async with sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    test_app.dependency_overrides[get_db] = _get_db
    return test_app, sessionmaker, engine


async def _seed_user(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    role: UserRole = UserRole.MEMBER,
    is_active: bool = True,
) -> User:
    user = User(
        username="alice",
        email="alice@example.com",
        hashed_password=hash_password("alice-pass"),
        role=role,
        is_active=is_active,
    )
    async with sessionmaker() as db:
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.mark.asyncio
async def test_valid_jwt_returns_user() -> None:
    """携带有效 JWT 应返回用户信息。"""
    test_app, sessionmaker, engine = await _build_app()
    try:
        user = await _seed_user(sessionmaker, role=UserRole.MEMBER)
        token = create_access_token(user.id)
        with TestClient(test_app) as client:
            resp = client.get(
                "/whoami", headers={"Authorization": f"Bearer {token}"}
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["id"] == user.id
        assert body["role"] == "member"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_expired_jwt_returns_401() -> None:
    """过期 JWT 应被 deps 拒为 401。"""
    test_app, sessionmaker, engine = await _build_app()
    try:
        user = await _seed_user(sessionmaker)
        token = create_access_token(user.id, expires_delta=timedelta(seconds=-60))
        with TestClient(test_app) as client:
            resp = client.get(
                "/whoami", headers={"Authorization": f"Bearer {token}"}
            )
        assert resp.status_code == 401, resp.text
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_tampered_jwt_returns_401() -> None:
    """用错误密钥签的 JWT 应被 deps 拒为 401。"""
    test_app, _sessionmaker, engine = await _build_app()
    try:
        bad_token = jwt.encode(
            {"sub": "evil", "exp": 9999999999},
            "this-is-not-the-real-secret",
            algorithm=ALGORITHM,
        )
        with TestClient(test_app) as client:
            resp = client.get(
                "/whoami", headers={"Authorization": f"Bearer {bad_token}"}
            )
        assert resp.status_code == 401, resp.text
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_unknown_user_returns_401() -> None:
    """JWT sub 指向 DB 里不存在的 user → 401（用户已被删除场景）。"""
    test_app, _sessionmaker, engine = await _build_app()
    try:
        token = create_access_token("uid-does-not-exist")
        with TestClient(test_app) as client:
            resp = client.get(
                "/whoami", headers={"Authorization": f"Bearer {token}"}
            )
        assert resp.status_code == 401, resp.text
        assert "User not found" in resp.json()["detail"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_inactive_user_returns_403() -> None:
    """is_active=False 的 user → 403（已登录但账号被禁用）。"""
    test_app, sessionmaker, engine = await _build_app()
    try:
        user = await _seed_user(sessionmaker, is_active=False)
        token = create_access_token(user.id)
        with TestClient(test_app) as client:
            resp = client.get(
                "/whoami", headers={"Authorization": f"Bearer {token}"}
            )
        assert resp.status_code == 403, resp.text
        assert "Inactive" in resp.json()["detail"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_static_fallback_with_matching_key_returns_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """env=True 且 Bearer == settings.api_key → 返回 _STATIC_ADMIN_USER。"""
    monkeypatch.setattr(settings, "jwt_fallback_to_static", True)
    monkeypatch.setattr(settings, "api_key", "static-admin-key-12345")

    test_app, _sessionmaker, engine = await _build_app()
    try:
        with TestClient(test_app) as client:
            resp = client.get(
                "/whoami",
                headers={"Authorization": "Bearer static-admin-key-12345"},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["role"] == "admin"
        assert body["id"] == "__static_fallback__"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_static_fallback_with_wrong_key_returns_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """env=True 但 Bearer 值与 settings.api_key 不匹配 → 401。"""
    monkeypatch.setattr(settings, "jwt_fallback_to_static", True)
    monkeypatch.setattr(settings, "api_key", "real-static-key")

    test_app, _sessionmaker, engine = await _build_app()
    try:
        with TestClient(test_app) as client:
            resp = client.get(
                "/whoami", headers={"Authorization": "Bearer wrong-key"}
            )
        assert resp.status_code == 401, resp.text
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_static_fallback_disabled_rejects_static_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """env=False 时即使 Bearer 等于 api_key 也应 401。"""
    monkeypatch.setattr(settings, "jwt_fallback_to_static", False)
    monkeypatch.setattr(settings, "api_key", "static-key-but-disabled")

    test_app, _sessionmaker, engine = await _build_app()
    try:
        with TestClient(test_app) as client:
            resp = client.get(
                "/whoami",
                headers={"Authorization": "Bearer static-key-but-disabled"},
            )
        assert resp.status_code == 401, resp.text
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_require_admin_blocks_member_with_403() -> None:
    """member 用户访问 ``/admin-only`` 应被 require_admin 拒为 403。"""
    test_app, sessionmaker, engine = await _build_app()
    try:
        user = await _seed_user(sessionmaker, role=UserRole.MEMBER)
        token = create_access_token(user.id)
        with TestClient(test_app) as client:
            resp = client.get(
                "/admin-only", headers={"Authorization": f"Bearer {token}"}
            )
        assert resp.status_code == 403, resp.text
        assert "admin" in resp.json()["detail"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_require_admin_allows_admin() -> None:
    """admin 用户访问 ``/admin-only`` 应通过。"""
    test_app, sessionmaker, engine = await _build_app()
    try:
        user = await _seed_user(sessionmaker, role=UserRole.ADMIN)
        token = create_access_token(user.id)
        with TestClient(test_app) as client:
            resp = client.get(
                "/admin-only", headers={"Authorization": f"Bearer {token}"}
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["role"] == "admin"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_no_credentials_returns_401() -> None:
    """既无 JWT 也无静态 token → 401 No credentials。"""
    test_app, _sessionmaker, engine = await _build_app()
    try:
        with TestClient(test_app) as client:
            resp = client.get("/whoami")
        assert resp.status_code == 401, resp.text
        assert "No credentials" in resp.json()["detail"]
    finally:
        await engine.dispose()
