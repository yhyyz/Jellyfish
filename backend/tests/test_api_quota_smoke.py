"""Smoke tests for the ``ApiKeyQuota`` model.

Verifies that the newly added ``ApiKeyQuota`` SQLAlchemy model:

- is importable from ``app.models.api_quota``;
- declares the ``api_key_quotas`` table name;
- uses ``api_key_hash`` as its single primary key;
- can be constructed with only the required-field kwargs.

This is a P1 schema-only guard — partner-API behaviour and runtime
quota enforcement land in P3 and are intentionally out of scope here.
"""

from __future__ import annotations

from datetime import date

from app.models.api_quota import ApiKeyQuota


def test_api_key_quota_tablename() -> None:
    """``ApiKeyQuota.__tablename__`` must be ``api_key_quotas``."""
    assert ApiKeyQuota.__tablename__ == "api_key_quotas"


def test_api_key_quota_primary_key_is_api_key_hash() -> None:
    """Only ``api_key_hash`` should participate in the primary key.

    A single-column PK keeps the contract simple: each hashed API key
    maps to exactly one quota row.
    """
    pk_columns = [col.name for col in ApiKeyQuota.__table__.primary_key.columns]
    assert pk_columns == ["api_key_hash"]

    api_key_hash_col = ApiKeyQuota.__table__.columns["api_key_hash"]
    assert api_key_hash_col.primary_key is True


def test_api_key_quota_construct_with_required_only() -> None:
    """Constructing ``ApiKeyQuota`` with required-only kwargs must succeed.

    Required fields here are ``api_key_hash`` (PK) and the two reset
    dates that have no Python-side default. All other columns rely on
    ORM ``default=`` values and must not be supplied.
    """
    today = date(2026, 1, 1)
    instance = ApiKeyQuota(
        api_key_hash="test-bcrypt-hash",
        last_reset_daily=today,
        last_reset_monthly=today,
    )

    assert instance.api_key_hash == "test-bcrypt-hash"
    assert instance.last_reset_daily == today
    assert instance.last_reset_monthly == today
