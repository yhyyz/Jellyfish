"""Tests for ``app.core.api_key_auth`` (P4 W24-T1).

This module exercises the per-key API authentication path that
sits in front of every ``/public/*`` request:

- bcrypt verification of the plaintext key against the
  ``api_key_quotas.api_key_hash`` column;
- atomic SQL quota deduction via
  ``UPDATE ... WHERE consumed_today < daily_limit RETURNING ...``
  (race-safe even under concurrent traffic);
- regression coverage proving that the legacy static-key path
  used by ``/api/v1/*`` admin endpoints is *not* broken when the
  new per-key path is enabled.

The tests are kept self-contained: each case spins up an in-memory
SQLite engine, seeds a single ``ApiKeyQuota`` row and overrides
``app.dependencies.get_db`` so the ``ApiKeyMiddleware`` and the
``/public/__test__/*`` helper route share the same database.
"""

# pylint: disable=invalid-name

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import AsyncGenerator

import bcrypt
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.models  # noqa: F401  pylint: disable=unused-import  ensure all models loaded

from app.core.api_key_auth import (
    BCRYPT_COST,
    consume_quota,
    verify_api_key,
)
from app.core.auth import ApiKeyMiddleware
from app.core.db import Base
from app.dependencies import get_db
from app.models.api_quota import ApiKeyQuota


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


async def _make_engine() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
    """Build a fresh in-memory SQLite engine + sessionmaker.

    A shared cache URI is used so that multiple sessions opened by
    the middleware and the route handler observe the same data
    rows (regular ``:memory:`` would give each connection its own
    private database).
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///file:test_api_key_auth?mode=memory&cache=shared&uri=true",
        future=True,
    )
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    return sessionmaker, engine


async def _seed_key(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    plaintext: str = "jellyfish_test_key_value",
    is_active: bool = True,
    daily_limit: int = 1000,
    consumed_today: int = 0,
    description: str = "test",
) -> str:
    """Persist a single ``ApiKeyQuota`` row and return the bcrypt hash."""
    today = datetime.now(UTC).date()
    api_key_hash = bcrypt.hashpw(
        plaintext.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_COST)
    ).decode("utf-8")
    async with sessionmaker() as session:
        session.add(
            ApiKeyQuota(
                api_key_hash=api_key_hash,
                description=description,
                daily_limit=daily_limit,
                monthly_limit=daily_limit * 30,
                rate_per_minute=60,
                consumed_today=consumed_today,
                consumed_this_month=0,
                last_reset_daily=today,
                last_reset_monthly=today,
                is_active=is_active,
            )
        )
        await session.commit()
    return api_key_hash


def _build_test_app(sessionmaker: async_sessionmaker[AsyncSession]) -> FastAPI:
    """Build a minimal FastAPI app wrapping ``ApiKeyMiddleware``.

    Provides:

    - ``GET /public/__test__/echo`` – consumes quota when called.
    - ``GET /public/__test__/status`` – quota-free path (suffix
      ``/status`` is whitelisted by the middleware).
    - ``GET /api/v1/__test__/legacy`` – legacy admin path that
      uses the static ``settings.api_key`` check.

    The test sessionmaker is wired in two places:

    - ``app.state.session_maker`` – picked up by
      :func:`enforce_public_request` so the middleware sees the
      same in-memory data as the route handlers.
    - ``app.dependency_overrides[get_db]`` – picked up by
      FastAPI route DI for any handler that depends on ``get_db``.
    """

    app = FastAPI()

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:  # noqa: BLE001
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    app.state.session_maker = sessionmaker
    app.add_middleware(ApiKeyMiddleware)

    @app.get("/public/__test__/echo")
    async def _public_echo(request: Request) -> dict[str, object]:
        return {"ok": True, "path": request.url.path}

    @app.get("/public/__test__/status")
    async def _public_status() -> dict[str, object]:
        return {"ok": True, "kind": "status"}

    @app.get("/api/v1/__test__/legacy")
    async def _legacy_admin() -> dict[str, object]:
        return {"ok": True, "path": "legacy"}

    return app


# ---------------------------------------------------------------------------
# 1) Valid key passes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_key_passes() -> None:
    """A request bearing a valid plaintext key should succeed and increment quota."""
    sessionmaker, engine = await _make_engine()
    plaintext = "jellyfish_valid_key_xyz"
    await _seed_key(sessionmaker, plaintext=plaintext, daily_limit=10)

    app = _build_test_app(sessionmaker)
    client = TestClient(app)
    response = client.get(
        "/public/__test__/echo", headers={"X-API-Key": plaintext}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True

    async with sessionmaker() as session:
        row = (await session.execute(select(ApiKeyQuota))).scalar_one()
        assert row.consumed_today == 1

    await engine.dispose()


# ---------------------------------------------------------------------------
# 2) Invalid key returns 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_key_returns_401() -> None:
    """A request whose plaintext does not match any stored hash → 401.

    Also covers the *missing* X-API-Key header sub-case: no header
    at all on a ``/public/*`` path must also produce 401.
    """
    sessionmaker, engine = await _make_engine()
    await _seed_key(sessionmaker, plaintext="jellyfish_real_key", daily_limit=10)

    app = _build_test_app(sessionmaker)
    client = TestClient(app)

    # wrong key
    response = client.get(
        "/public/__test__/echo", headers={"X-API-Key": "jellyfish_wrong"}
    )
    assert response.status_code == 401, response.text

    # missing header
    response_missing = client.get("/public/__test__/echo")
    assert response_missing.status_code == 401, response_missing.text

    await engine.dispose()


# ---------------------------------------------------------------------------
# 3) Inactive key returns 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inactive_key_returns_403() -> None:
    """A revoked (``is_active=False``) key must reject with 403, not 401."""
    sessionmaker, engine = await _make_engine()
    plaintext = "jellyfish_revoked"
    await _seed_key(sessionmaker, plaintext=plaintext, is_active=False)

    app = _build_test_app(sessionmaker)
    client = TestClient(app)
    response = client.get(
        "/public/__test__/echo", headers={"X-API-Key": plaintext}
    )
    assert response.status_code == 403, response.text

    await engine.dispose()


# ---------------------------------------------------------------------------
# 4) Quota exhausted returns 429 with Retry-After
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expired_quota_returns_429_with_retry_after() -> None:
    """When ``consumed_today >= daily_limit`` the middleware returns 429.

    The response must carry a ``Retry-After`` header so SaaS callers can
    back off until the daily window resets.
    """
    sessionmaker, engine = await _make_engine()
    plaintext = "jellyfish_exhausted"
    await _seed_key(
        sessionmaker,
        plaintext=plaintext,
        daily_limit=5,
        consumed_today=5,
    )

    app = _build_test_app(sessionmaker)
    client = TestClient(app)
    response = client.get(
        "/public/__test__/echo", headers={"X-API-Key": plaintext}
    )
    assert response.status_code == 429, response.text
    assert "Retry-After" in response.headers
    assert response.headers["Retry-After"]  # non-empty

    await engine.dispose()


# ---------------------------------------------------------------------------
# 5) Atomic counter (50 concurrent vs daily_limit=50)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_atomic_counter_no_race() -> None:
    """50 concurrent ``consume_quota`` calls vs ``daily_limit=50``.

    The atomic ``UPDATE ... WHERE consumed_today < daily_limit``
    statement guarantees:

    - all 50 calls succeed (return ``True``);
    - final ``consumed_today`` lands on exactly 50, never 51.

    Without the WHERE-clause guard a naive read-modify-write would
    overshoot under concurrent traffic; this test is the canary
    for that regression.
    """
    sessionmaker, engine = await _make_engine()
    plaintext = "jellyfish_race_target"
    api_key_hash = await _seed_key(
        sessionmaker,
        plaintext=plaintext,
        daily_limit=50,
        consumed_today=0,
    )

    async def _one_call() -> bool:
        async with sessionmaker() as session:
            return await consume_quota(session, api_key_hash)

    results = await asyncio.gather(*[_one_call() for _ in range(50)])
    assert all(results), f"some calls were rejected: {results}"

    async with sessionmaker() as session:
        row = (await session.execute(select(ApiKeyQuota))).scalar_one()
        assert row.consumed_today == 50, (
            f"expected consumed_today=50, got {row.consumed_today}"
        )

    # one more call past the limit must fail (rowcount=0 path)
    async with sessionmaker() as session:
        assert await consume_quota(session, api_key_hash) is False

    await engine.dispose()


# ---------------------------------------------------------------------------
# 6) Legacy admin path with static API key remains unchanged (regression)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_admin_path_static_key_unchanged() -> None:
    """``/api/v1/*`` paths must keep using the static ``settings.api_key``.

    This guards the P1 contract: when an operator already wired
    ``API_KEY=...`` into their deployment, the new per-key path
    must not accidentally start bcrypt-verifying the static key.
    """
    sessionmaker, engine = await _make_engine()

    await _seed_key(sessionmaker, plaintext="jellyfish_unrelated_public_key")

    from app.config import settings as _settings

    static_key = "static-admin-key-secret"
    original_api_key = _settings.api_key
    _settings.api_key = static_key
    try:
        app = _build_test_app(sessionmaker)
        client = TestClient(app)

        response_ok = client.get(
            "/api/v1/__test__/legacy", headers={"X-API-Key": static_key}
        )
        assert response_ok.status_code == 200, response_ok.text
        assert response_ok.json()["ok"] is True

        response_bad = client.get(
            "/api/v1/__test__/legacy", headers={"X-API-Key": "wrong"}
        )
        assert response_bad.status_code == 401, response_bad.text

        response_bcrypt_attack = client.get(
            "/api/v1/__test__/legacy",
            headers={"X-API-Key": "jellyfish_unrelated_public_key"},
        )
        assert response_bcrypt_attack.status_code == 401, response_bcrypt_attack.text
    finally:
        _settings.api_key = original_api_key
        await engine.dispose()


# ---------------------------------------------------------------------------
# Bonus: /public/.../status should not deduct quota.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_path_skips_quota_deduction() -> None:
    """Status query paths under ``/public/*`` are quota-free.

    They still require a valid bcrypt-matched X-API-Key (so leaks
    are still attributable), but should not burn quota — clients
    poll status frequently and would otherwise self-DoS.
    """
    sessionmaker, engine = await _make_engine()
    plaintext = "jellyfish_status_caller"
    await _seed_key(
        sessionmaker, plaintext=plaintext, daily_limit=1, consumed_today=0
    )

    app = _build_test_app(sessionmaker)
    client = TestClient(app)
    for _ in range(5):
        response = client.get(
            "/public/__test__/status", headers={"X-API-Key": plaintext}
        )
        assert response.status_code == 200, response.text

    async with sessionmaker() as session:
        row = (await session.execute(select(ApiKeyQuota))).scalar_one()
        assert row.consumed_today == 0

    await engine.dispose()


# ---------------------------------------------------------------------------
# Bonus: verify_api_key returns None for unknown plaintext.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_api_key_returns_none_for_unknown() -> None:
    sessionmaker, engine = await _make_engine()
    await _seed_key(sessionmaker, plaintext="jellyfish_seed")

    async with sessionmaker() as session:
        assert await verify_api_key(session, "jellyfish_other") is None
        assert await verify_api_key(session, "") is None

    await engine.dispose()
