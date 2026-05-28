"""Tests for ``app.tasks.quota_reset`` (P4 W24-T4).

覆盖三件事：

1. 日重置把 ``consumed_today`` 归零并推进 ``last_reset_daily``；
2. 月重置只动 ``consumed_this_month``，不影响 ``consumed_today``；
3. ``is_active=False`` 的历史 key 不被任一重置任务触碰。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401  pylint: disable=unused-import

from app.core.db import Base
from app.models.api_quota import ApiKeyQuota
from app.tasks.quota_reset import (
    reset_daily_quotas_sync,
    reset_monthly_quotas_sync,
)


def _make_sync_sessionmaker():
    """构造每个 case 隔离的 in-memory SQLite sessionmaker。"""

    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
    )
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


def _seed(
    maker,
    *,
    api_key_hash: str,
    consumed_today: int = 0,
    consumed_this_month: int = 0,
    last_reset_daily: date | None = None,
    last_reset_monthly: date | None = None,
    is_active: bool = True,
) -> None:
    today = datetime.now(UTC).date()
    with maker() as session:
        session.add(
            ApiKeyQuota(
                api_key_hash=api_key_hash,
                description="t",
                daily_limit=1000,
                monthly_limit=30000,
                rate_per_minute=60,
                consumed_today=consumed_today,
                consumed_this_month=consumed_this_month,
                last_reset_daily=last_reset_daily or today - timedelta(days=2),
                last_reset_monthly=last_reset_monthly or today.replace(day=1) - timedelta(days=40),
                is_active=is_active,
            )
        )
        session.commit()


def test_daily_reset_zeros_consumed_today() -> None:
    """日重置必须把 active key 的 ``consumed_today`` 清零并推进水位线。"""
    maker = _make_sync_sessionmaker()
    _seed(maker, api_key_hash="hash_a", consumed_today=500, consumed_this_month=2000)

    affected = reset_daily_quotas_sync(maker)

    assert affected == 1
    today = datetime.now(UTC).date()
    with maker() as session:
        row = session.execute(select(ApiKeyQuota)).scalar_one()
        assert row.consumed_today == 0
        assert row.last_reset_daily == today
        # 月度计数不应被日重置影响。
        assert row.consumed_this_month == 2000


def test_monthly_reset_zeros_consumed_this_month_only() -> None:
    """月重置仅清零 ``consumed_this_month``，不动 ``consumed_today``。"""
    maker = _make_sync_sessionmaker()
    _seed(maker, api_key_hash="hash_b", consumed_today=300, consumed_this_month=15000)

    affected = reset_monthly_quotas_sync(maker)

    assert affected == 1
    today = datetime.now(UTC).date()
    with maker() as session:
        row = session.execute(select(ApiKeyQuota)).scalar_one()
        assert row.consumed_this_month == 0
        assert row.last_reset_monthly == today.replace(day=1)
        # 日计数应保持原值。
        assert row.consumed_today == 300


def test_inactive_keys_not_touched() -> None:
    """``is_active=False`` 的历史行不能被日/月重置任务修改。

    保留计数与水位线用于事后审计；同时验证 active key 仍被正常重置。
    """
    maker = _make_sync_sessionmaker()
    historical_daily = date(2024, 1, 1)
    historical_monthly = date(2024, 1, 1)
    _seed(
        maker,
        api_key_hash="hash_inactive",
        consumed_today=999,
        consumed_this_month=29999,
        last_reset_daily=historical_daily,
        last_reset_monthly=historical_monthly,
        is_active=False,
    )
    _seed(
        maker,
        api_key_hash="hash_active",
        consumed_today=10,
        consumed_this_month=100,
    )

    daily_affected = reset_daily_quotas_sync(maker)
    monthly_affected = reset_monthly_quotas_sync(maker)

    assert daily_affected == 1
    assert monthly_affected == 1

    with maker() as session:
        inactive = session.get(ApiKeyQuota, "hash_inactive")
        active = session.get(ApiKeyQuota, "hash_active")
        assert inactive is not None and active is not None
        assert inactive.consumed_today == 999
        assert inactive.consumed_this_month == 29999
        assert inactive.last_reset_daily == historical_daily
        assert inactive.last_reset_monthly == historical_monthly
        assert active.consumed_today == 0
        assert active.consumed_this_month == 0


def test_celery_tasks_registered_with_expected_names() -> None:
    """W24-T4 契约：beat_schedule 引用的任务名必须真实存在。"""
    from app.core.celery_app import celery_app
    import app.tasks.quota_reset  # noqa: F401  ensure registration

    assert "task.quota.reset_daily" in celery_app.tasks
    assert "task.quota.reset_monthly" in celery_app.tasks


def test_beat_schedule_uses_redbeat_scheduler() -> None:
    """W24-T4 契约：scheduler 必须是 RedBeat（多副本安全）。"""
    from app.core.celery_app import celery_app

    assert celery_app.conf.beat_scheduler == "redbeat.RedBeatScheduler"
    schedule = celery_app.conf.beat_schedule
    assert "reset-daily-quotas" in schedule
    assert "reset-monthly-quotas" in schedule
    assert schedule["reset-daily-quotas"]["task"] == "task.quota.reset_daily"
    assert schedule["reset-monthly-quotas"]["task"] == "task.quota.reset_monthly"
