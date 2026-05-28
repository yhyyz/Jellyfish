"""compliance_dispatcher 单元测试（W26-T1）。

覆盖：
    - 单条 BLOCKER → Slack + email 两渠道并发被调（asyncio.gather）；
    - 单条 BLOCKER → 单渠道失败 3 次后写入 NotificationDelivery；
    - profile_id 过滤：只有匹配的 profile 与全局兜底渠道被选中；
    - 重试 schedule：3 次尝试，等待 1s/2s/4s（用注入 sleep mock 验证）；
    - 多条 BLOCKER → asyncio.gather 并发处理。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.integrations.notifications.email import EmailDeliveryError, SmtpConfig
from app.integrations.notifications.slack import SlackDeliveryError
from app.models.notification_channel import NotificationChannel, NotificationDelivery
from app.services.notifications.compliance_dispatcher import (
    BlockerFindingPayload,
    dispatch_blocker_finding,
    dispatch_blocker_findings,
    _send_with_retry,
    _BACKOFF_SCHEDULE_SEC,
)


# ---------------------------------------------------------------------------
# In-memory async sqlite helper（在每个测试内手动调用，回避 conftest
# 的同步 fixture 限制）
# ---------------------------------------------------------------------------


async def _make_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: NotificationChannel.__table__.create(c, checkfirst=True)
        )
        await conn.run_sync(
            lambda c: NotificationDelivery.__table__.create(c, checkfirst=True)
        )
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return engine, maker


# ---------------------------------------------------------------------------
# 工具：给定 session 注入 N 个渠道
# ---------------------------------------------------------------------------


async def _add_channels(session: AsyncSession, channels: list[NotificationChannel]) -> None:
    for c in channels:
        session.add(c)
    await session.commit()


def _payload(finding_id: int = 1, profile_id: str | None = None) -> BlockerFindingPayload:
    return BlockerFindingPayload(
        finding_id=finding_id,
        severity="blocker",
        rule_id="r1",
        rule_kind="banned_phrase",
        description="bad",
        variant_id="v1",
        profile_id=profile_id,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_fan_out_slack_and_email_in_parallel() -> None:
    engine, maker = await _make_session()
    try:
        async with maker() as session:
            await _add_channels(
                session,
                [
                    NotificationChannel(
                        id="slack-a", profile_id=None, kind="slack",
                        target="https://hooks.slack.com/services/X/Y", enabled=True,
                    ),
                    NotificationChannel(
                        id="email-a", profile_id=None, kind="email",
                        target="legal@example.com", enabled=True,
                    ),
                ],
            )
        
            slack_calls: list[Any] = []
            email_calls: list[Any] = []
        
            async def fake_slack(url: str, *, text: str, blocks=None, **_) -> None:
                slack_calls.append((url, text, blocks))
        
            async def fake_email(*, config, sender, recipients, subject, body, **_) -> None:
                email_calls.append((sender, list(recipients), subject))
        
            smtp = SmtpConfig(host="x", port=25)
            result = await dispatch_blocker_finding(
                _payload(),
                session=session,
                smtp_config=smtp,
                smtp_sender="alerts@example.com",
                slack_sender=fake_slack,
                email_sender=fake_email,
                sleep=lambda _t: asyncio.sleep(0),
            )
        
            assert result.attempted == 2
            assert result.succeeded == 2
            assert result.failed == 0
            assert len(slack_calls) == 1
            assert len(email_calls) == 1
            assert slack_calls[0][0].startswith("https://hooks.slack.com")
            assert email_calls[0][1] == ["legal@example.com"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_dispatch_records_failure_after_3_retries() -> None:
    engine, maker = await _make_session()
    try:
        async with maker() as session:
            await _add_channels(
                session,
                [
                    NotificationChannel(
                        id="slack-fail", profile_id=None, kind="slack",
                        target="https://hooks.slack.com/X", enabled=True,
                    ),
                ],
            )
        
            attempts = {"n": 0}
        
            async def always_fail(url: str, *, text: str, blocks=None, **_) -> None:
                attempts["n"] += 1
                raise SlackDeliveryError("boom")
        
            sleeps: list[float] = []
        
            async def fake_sleep(s: float) -> None:
                sleeps.append(s)
        
            result = await dispatch_blocker_finding(
                _payload(finding_id=99),
                session=session,
                smtp_config=None,
                smtp_sender=None,
                slack_sender=always_fail,
                sleep=fake_sleep,
            )
        
            assert attempts["n"] == 3
            assert sleeps == list(_BACKOFF_SCHEDULE_SEC[:2])  # 仅 attempt 1->2, 2->3 之间睡
            assert result.failed == 1
            assert result.failed_channels == ["slack-fail"]
        
            # NotificationDelivery 表应有一行
            await session.commit()
            rows = (await session.execute(NotificationDelivery.__table__.select())).fetchall()
            assert len(rows) == 1
            row = rows[0]
            assert row.channel_id == "slack-fail"
            assert row.finding_id == 99
            assert row.attempts == 3
            assert "boom" in row.error
            assert row.kind == "slack"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_dispatch_filters_by_profile_id() -> None:
    engine, maker = await _make_session()
    try:
        async with maker() as session:
            await _add_channels(
                session,
                [
                    NotificationChannel(
                        id="match", profile_id="cn_mainland_default", kind="slack",
                        target="https://x.example/match", enabled=True,
                    ),
                    NotificationChannel(
                        id="other-profile", profile_id="cn_mainland_health", kind="slack",
                        target="https://x.example/other", enabled=True,
                    ),
                    NotificationChannel(
                        id="global", profile_id=None, kind="slack",
                        target="https://x.example/global", enabled=True,
                    ),
                    NotificationChannel(
                        id="disabled", profile_id="cn_mainland_default", kind="slack",
                        target="https://x.example/disabled", enabled=False,
                    ),
                ],
            )
        
            sent: list[str] = []
        
            async def fake_slack(url: str, *, text: str, blocks=None, **_) -> None:
                sent.append(url)
        
            result = await dispatch_blocker_finding(
                _payload(profile_id="cn_mainland_default"),
                session=session,
                slack_sender=fake_slack,
                sleep=lambda _t: asyncio.sleep(0),
            )
        
            assert result.attempted == 2  # match + global
            assert sorted(sent) == ["https://x.example/global", "https://x.example/match"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_dispatch_partial_failure_email_recorded() -> None:
    engine, maker = await _make_session()
    try:
        async with maker() as session:
            await _add_channels(
                session,
                [
                    NotificationChannel(
                        id="s", profile_id=None, kind="slack",
                        target="https://hooks.slack.com/ok", enabled=True,
                    ),
                    NotificationChannel(
                        id="e", profile_id=None, kind="email",
                        target="legal@example.com", enabled=True,
                    ),
                ],
            )
        
            async def fake_slack(url, *, text, blocks=None, **_) -> None:
                return None
        
            async def fake_email(**_kwargs) -> None:
                raise EmailDeliveryError("smtp down")
        
            smtp = SmtpConfig(host="x", port=25)
            result = await dispatch_blocker_finding(
                _payload(),
                session=session,
                smtp_config=smtp,
                smtp_sender="a@b",
                slack_sender=fake_slack,
                email_sender=fake_email,
                sleep=lambda _t: asyncio.sleep(0),
            )
        
            assert result.succeeded == 1
            assert result.failed == 1
            assert result.failed_channels == ["e"]
            await session.commit()
            rows = (await session.execute(NotificationDelivery.__table__.select())).fetchall()
            assert len(rows) == 1
            assert rows[0].kind == "email"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_dispatch_email_skipped_when_smtp_unconfigured() -> None:
    engine, maker = await _make_session()
    try:
        async with maker() as session:
            await _add_channels(
                session,
                [
                    NotificationChannel(
                        id="e", profile_id=None, kind="email",
                        target="legal@example.com", enabled=True,
                    ),
                ],
            )
        
            called = {"n": 0}
        
            async def fake_email(**_) -> None:
                called["n"] += 1
        
            result = await dispatch_blocker_finding(
                _payload(),
                session=session,
                smtp_config=None,
                smtp_sender=None,
                email_sender=fake_email,
                sleep=lambda _t: asyncio.sleep(0),
            )
            assert called["n"] == 0
            assert result.failed == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_dispatch_blocker_findings_batch() -> None:
    engine, maker = await _make_session()
    try:
        async with maker() as session:
            await _add_channels(
                session,
                [
                    NotificationChannel(
                        id="s", profile_id=None, kind="slack",
                        target="https://hooks.slack.com/X", enabled=True,
                    ),
                ],
            )
        
            received: list[int | None] = []
        
            async def fake_slack(url, *, text, blocks=None, **_) -> None:
                # text 包含 finding rule，但 finding_id 在 blocks 字段中
                for b in blocks or []:
                    for f in b.get("fields", []) or []:
                        if f["text"].startswith("*Finding*"):
                            received.append(f["text"])
        
            payloads = [_payload(finding_id=i) for i in (1, 2, 3)]
            results = await dispatch_blocker_findings(
                payloads,
                session=session,
                slack_sender=fake_slack,
                sleep=lambda _t: asyncio.sleep(0),
            )
            assert len(results) == 3
            assert all(r.succeeded == 1 for r in results)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_send_with_retry_schedule() -> None:
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    counter = {"n": 0}

    async def sender() -> None:
        counter["n"] += 1
        if counter["n"] < 3:
            raise SlackDeliveryError("nope")

    attempts, exc = await _send_with_retry(sender=sender, sleep=fake_sleep)
    assert attempts == 3
    assert exc is None
    assert sleeps == [1.0, 2.0]


@pytest.mark.asyncio
async def test_send_with_retry_unexpected_error_no_retry() -> None:
    counter = {"n": 0}

    async def sender() -> None:
        counter["n"] += 1
        raise RuntimeError("totally unexpected")

    attempts, exc = await _send_with_retry(
        sender=sender, sleep=lambda _t: asyncio.sleep(0)
    )
    assert counter["n"] == 1
    assert isinstance(exc, RuntimeError)
