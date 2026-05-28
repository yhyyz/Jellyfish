"""Tests for ``app.services.api_quota.quota_service`` (P4 W24-T1).

This module covers the security-critical contract of the quota
service:

- creating a key returns the **plaintext exactly once** and the DB
  retains only its bcrypt hash;
- revoking a key flips ``is_active=False`` instantly (subsequent
  list queries should not surface it through the active-only
  default filter);
- bcrypt hashes are not reversible: re-hashing the same plaintext
  yields a *different* hash (random salt) and the stored hash never
  contains the plaintext substring;
- listing excludes revoked keys by default but can include them
  when explicitly opted-in.
"""

# pylint: disable=invalid-name

from __future__ import annotations

import bcrypt
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  pylint: disable=unused-import

from app.core.db import Base
from app.models.api_quota import ApiKeyQuota
from app.services.api_quota.quota_service import (
    KEY_PLAINTEXT_PREFIX,
    create_api_key,
    get_usage,
    list_api_keys,
    revoke_api_key,
)


async def _make_session() -> tuple[AsyncSession, object]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return sessionmaker(), engine


# ---------------------------------------------------------------------------
# 1) plaintext is returned exactly once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_key_returns_plaintext_once_then_only_hash() -> None:
    """``create_api_key`` returns the plaintext key once.

    After the call:

    - The plaintext key is **never** persisted (DB row only stores
      bcrypt hash).
    - Subsequent reads (``list_api_keys`` / ``get_usage``) only
      surface the bcrypt hash; there is no path to recover plaintext.
    - The returned plaintext starts with the canonical
      ``jellyfish_`` prefix so SaaS callers can recognise it.
    """
    db, engine = await _make_session()
    async with db:
        plaintext, row = await create_api_key(
            db,
            description="partner-alpha",
            daily_limit=100,
            monthly_limit=2000,
            rate_per_minute=10,
        )

        # plaintext format
        assert plaintext.startswith(KEY_PLAINTEXT_PREFIX)
        assert len(plaintext) > len(KEY_PLAINTEXT_PREFIX) + 16

        # hash stored, plaintext not stored anywhere
        assert row.api_key_hash != plaintext
        assert plaintext not in row.api_key_hash
        assert row.api_key_hash.startswith("$2b$")  # bcrypt format

        # description and limits round-trip
        assert row.description == "partner-alpha"
        assert row.daily_limit == 100
        assert row.monthly_limit == 2000
        assert row.rate_per_minute == 10
        assert row.is_active is True
        assert row.consumed_today == 0
        assert row.consumed_this_month == 0

        # raw column inspection: plaintext absent from any column
        all_rows = (await db.execute(select(ApiKeyQuota))).scalars().all()
        assert len(all_rows) == 1
        for column_value in (
            all_rows[0].api_key_hash,
            all_rows[0].description,
        ):
            assert plaintext not in str(column_value)

        # bcrypt round-trip works (hash matches plaintext)
        assert bcrypt.checkpw(
            plaintext.encode("utf-8"), row.api_key_hash.encode("utf-8")
        )
    await engine.dispose()


# ---------------------------------------------------------------------------
# 2) revoke flips is_active immediately
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_disables_key_immediately() -> None:
    """``revoke_api_key`` sets ``is_active=False`` and persists synchronously."""
    db, engine = await _make_session()
    async with db:
        _plaintext, row = await create_api_key(db, description="will-revoke")
        api_key_hash = row.api_key_hash

        revoked = await revoke_api_key(db, api_key_hash=api_key_hash)
        assert revoked is not None
        assert revoked.is_active is False

        # Re-read from DB to confirm persistence (not just an in-memory flip).
        await db.commit()
        re_read = (
            await db.execute(
                select(ApiKeyQuota).where(ApiKeyQuota.api_key_hash == api_key_hash)
            )
        ).scalar_one()
        assert re_read.is_active is False

        # revoking an unknown hash returns None (idempotent semantics)
        assert await revoke_api_key(db, api_key_hash="$2b$12$nonexistent") is None
    await engine.dispose()


# ---------------------------------------------------------------------------
# 3) bcrypt hash is not reversible
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bcrypt_hash_not_reversible() -> None:
    """The bcrypt hash must hide the plaintext.

    Concretely:

    - The hash must not contain the plaintext as a substring.
    - Re-hashing the same plaintext yields a *different* hash
      because bcrypt salts each output (so static lookup by hash
      from plaintext is impossible without bcrypt verification).
    """
    db, engine = await _make_session()
    async with db:
        plaintext_a, row_a = await create_api_key(db, description="a")
        plaintext_b, row_b = await create_api_key(db, description="b")

        # No leak of plaintext.
        assert plaintext_a not in row_a.api_key_hash
        assert plaintext_b not in row_b.api_key_hash

        # Different keys produce different hashes (random salts).
        assert row_a.api_key_hash != row_b.api_key_hash
        assert plaintext_a != plaintext_b

        # Re-hashing the SAME plaintext must produce a DIFFERENT hash
        # (bcrypt salt randomness — proves stored hash is salted).
        rehash = bcrypt.hashpw(
            plaintext_a.encode("utf-8"), bcrypt.gensalt(rounds=12)
        ).decode("utf-8")
        assert rehash != row_a.api_key_hash
        # but both verify against the same plaintext
        assert bcrypt.checkpw(plaintext_a.encode("utf-8"), rehash.encode("utf-8"))
        assert bcrypt.checkpw(
            plaintext_a.encode("utf-8"), row_a.api_key_hash.encode("utf-8")
        )
    await engine.dispose()


# ---------------------------------------------------------------------------
# 4) list_api_keys excludes revoked by default
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_keys_excludes_revoked() -> None:
    """``list_api_keys`` defaults to active-only; opt-in for full view."""
    db, engine = await _make_session()
    async with db:
        _, row_alive = await create_api_key(db, description="alive")
        _, row_dead = await create_api_key(db, description="dead")
        await revoke_api_key(db, api_key_hash=row_dead.api_key_hash)
        await db.commit()

        active_only = await list_api_keys(db)
        active_hashes = {r.api_key_hash for r in active_only}
        assert row_alive.api_key_hash in active_hashes
        assert row_dead.api_key_hash not in active_hashes

        all_keys = await list_api_keys(db, include_inactive=True)
        all_hashes = {r.api_key_hash for r in all_keys}
        assert {row_alive.api_key_hash, row_dead.api_key_hash} <= all_hashes
    await engine.dispose()


# ---------------------------------------------------------------------------
# Bonus: get_usage returns the same row by hash.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_usage_returns_row_by_hash() -> None:
    db, engine = await _make_session()
    async with db:
        _plaintext, row = await create_api_key(
            db, description="usage", daily_limit=200
        )
        usage = await get_usage(db, api_key_hash=row.api_key_hash)
        assert usage is not None
        assert usage.api_key_hash == row.api_key_hash
        assert usage.daily_limit == 200
        assert usage.consumed_today == 0

        assert await get_usage(db, api_key_hash="$2b$12$missing") is None
    await engine.dispose()
