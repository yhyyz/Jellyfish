"""escalation_engine 单元测试（W26-T2）。

覆盖至少 4 个 TDD case：

    1. ``test_under_threshold_no_escalation``：连续 N-1 条 BLOCKER 不触发；
    2. ``test_at_threshold_triggers_escalation``：恰好到达阈值时触发，并
       发出 owner 邮件；
    3. ``test_over_threshold_does_not_double_fire``：触发后窗口被重置，
       后续单条 BLOCKER 不再连续触发；
    4. ``test_window_reset``：窗口超时（24h+1m）后计数器从 0 开始。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.integrations.notifications.email import SmtpConfig
from app.models.compliance import ComplianceProfile
from app.models.escalation_state import EscalationState
from app.services.notifications.escalation_engine import (
    DEFAULT_THRESHOLD,
    DEFAULT_WINDOW_HOURS,
    EscalationInput,
    _extract_config_from_rules,
    maybe_escalate,
)


# ---------------------------------------------------------------------------
# In-memory async sqlite helper
# ---------------------------------------------------------------------------


async def _make_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: ComplianceProfile.__table__.create(c, checkfirst=True)
        )
        await conn.run_sync(
            lambda c: EscalationState.__table__.create(c, checkfirst=True)
        )
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return engine, maker


def _smtp_config() -> SmtpConfig:
    return SmtpConfig(
        host="smtp.example.com",
        port=587,
        username="bot@example.com",
        password="secret",
        start_tls=True,
        sender="bot@example.com",
    )


def _payload(profile_id: str = "p1", finding_id: int = 1) -> EscalationInput:
    return EscalationInput(
        finding_id=finding_id,
        rule_id="r1",
        description="bad",
        profile_id=profile_id,
        team_id=None,
        variant_id="v1",
    )


class _SpyEmailSender:
    """记录调用次数与最后一次入参的 email_sender 替身。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


# ---------------------------------------------------------------------------
# 配置解析单测（保护 DEFAULT 行为）
# ---------------------------------------------------------------------------


def test_extract_config_defaults_when_rules_empty() -> None:
    cfg = _extract_config_from_rules([])
    assert cfg.threshold == DEFAULT_THRESHOLD
    assert cfg.window_hours == DEFAULT_WINDOW_HOURS


def test_extract_config_from_rules_list_entry() -> None:
    rules = [
        {"id": "x", "kind": "banned_phrase"},
        {"escalation": {"threshold": 5, "window_hours": 6}},
    ]
    cfg = _extract_config_from_rules(rules)
    assert cfg.threshold == 5
    assert cfg.window_hours == 6


def test_extract_config_from_dict_root() -> None:
    rules = {"escalation": {"threshold": 2, "window_hours": 1}}
    cfg = _extract_config_from_rules(rules)
    assert cfg.threshold == 2
    assert cfg.window_hours == 1


# ---------------------------------------------------------------------------
# 行为单测：4 个核心 case
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_under_threshold_no_escalation() -> None:
    """阈值之下：N-1 次 BLOCKER 不触发，也不发 owner 邮件。"""

    engine, maker = await _make_session()
    spy = _SpyEmailSender()
    base_now = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

    async with maker() as session:
        for i in range(DEFAULT_THRESHOLD - 1):
            outcome = await maybe_escalate(
                session,
                _payload(finding_id=i + 1),
                smtp_config=_smtp_config(),
                smtp_sender="bot@example.com",
                owner_email="owner@example.com",
                now=base_now + timedelta(minutes=i),
                email_sender=spy,
            )
            assert outcome.counted is True
            assert outcome.triggered is False
        await session.commit()

    assert spy.calls == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_at_threshold_triggers_escalation() -> None:
    """恰好到达阈值：触发 owner 通知，且状态被重置。"""

    engine, maker = await _make_session()
    spy = _SpyEmailSender()
    base_now = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

    async with maker() as session:
        last_outcome = None
        for i in range(DEFAULT_THRESHOLD):
            last_outcome = await maybe_escalate(
                session,
                _payload(finding_id=i + 1),
                smtp_config=_smtp_config(),
                smtp_sender="bot@example.com",
                owner_email="owner@example.com",
                now=base_now + timedelta(minutes=i),
                email_sender=spy,
            )
        await session.commit()

        assert last_outcome is not None
        assert last_outcome.triggered is True
        assert len(spy.calls) == 1
        call = spy.calls[0]
        assert call["recipients"] == ["owner@example.com"]
        assert "Escalation" in call["subject"]

        state = (
            await session.execute(
                EscalationState.__table__.select().where(
                    EscalationState.id == "profile:p1"
                )
            )
        ).first()
        assert state is not None
        assert state._mapping["consecutive_blockers"] == 0
        assert state._mapping["window_start_at"] is None
        assert state._mapping["last_escalated_at"] is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_over_threshold_does_not_double_fire() -> None:
    """触发后立刻再来一条 BLOCKER 不应连续触发（窗口已被重置）。"""

    engine, maker = await _make_session()
    spy = _SpyEmailSender()
    base_now = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

    async with maker() as session:
        for i in range(DEFAULT_THRESHOLD + 1):
            await maybe_escalate(
                session,
                _payload(finding_id=i + 1),
                smtp_config=_smtp_config(),
                smtp_sender="bot@example.com",
                owner_email="owner@example.com",
                now=base_now + timedelta(seconds=i),
                email_sender=spy,
            )
        await session.commit()

    assert len(spy.calls) == 1, "trigger 后应立即重置，不应连续触发"
    await engine.dispose()


@pytest.mark.asyncio
async def test_window_reset() -> None:
    """窗口超时（24h+1m）后计数器从 1 开始重新计算。"""

    engine, maker = await _make_session()
    spy = _SpyEmailSender()
    t0 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

    async with maker() as session:
        out1 = await maybe_escalate(
            session,
            _payload(finding_id=1),
            smtp_config=_smtp_config(),
            smtp_sender="bot@example.com",
            owner_email="owner@example.com",
            now=t0,
            email_sender=spy,
        )
        out2 = await maybe_escalate(
            session,
            _payload(finding_id=2),
            smtp_config=_smtp_config(),
            smtp_sender="bot@example.com",
            owner_email="owner@example.com",
            now=t0 + timedelta(minutes=1),
            email_sender=spy,
        )
        out3 = await maybe_escalate(
            session,
            _payload(finding_id=3),
            smtp_config=_smtp_config(),
            smtp_sender="bot@example.com",
            owner_email="owner@example.com",
            now=t0 + timedelta(hours=DEFAULT_WINDOW_HOURS, minutes=1),
            email_sender=spy,
        )
        await session.commit()

    assert out1.consecutive_blockers == 1
    assert out2.consecutive_blockers == 2
    assert out3.consecutive_blockers == 1, "窗口超时后应从 1 开始重新计数"
    assert out3.triggered is False
    assert spy.calls == []
    await engine.dispose()


# ---------------------------------------------------------------------------
# 补充：profile.rules 中自定义阈值生效
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_custom_threshold_from_profile_rules() -> None:
    """profile.rules 含 escalation 配置时，自定义 threshold 应生效。"""

    engine, maker = await _make_session()
    spy = _SpyEmailSender()
    base_now = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

    async with maker() as session:
        session.add(
            ComplianceProfile(
                id="p_custom",
                name="custom",
                region="cn_mainland",
                rules=[{"escalation": {"threshold": 2, "window_hours": 1}}],
                is_system=True,
                description="",
            )
        )
        await session.commit()

        out1 = await maybe_escalate(
            session,
            _payload(profile_id="p_custom", finding_id=1),
            smtp_config=_smtp_config(),
            smtp_sender="bot@example.com",
            owner_email="owner@example.com",
            now=base_now,
            email_sender=spy,
        )
        out2 = await maybe_escalate(
            session,
            _payload(profile_id="p_custom", finding_id=2),
            smtp_config=_smtp_config(),
            smtp_sender="bot@example.com",
            owner_email="owner@example.com",
            now=base_now + timedelta(minutes=1),
            email_sender=spy,
        )
        await session.commit()

    assert out1.triggered is False
    assert out2.triggered is True
    assert len(spy.calls) == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_no_scope_skips_engine() -> None:
    """profile_id 与 team_id 全空时不参与升级判定（避免全局桶被滥用）。"""

    engine, maker = await _make_session()
    spy = _SpyEmailSender()

    async with maker() as session:
        outcome = await maybe_escalate(
            session,
            EscalationInput(
                finding_id=1,
                rule_id="r1",
                description="d",
                profile_id=None,
                team_id=None,
            ),
            smtp_config=_smtp_config(),
            smtp_sender="bot@example.com",
            owner_email="owner@example.com",
            email_sender=spy,
        )

    assert outcome.counted is False
    assert outcome.triggered is False
    assert outcome.skipped_reason == "no scope"
    assert spy.calls == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_triggered_without_owner_email_skips_notify_but_resets() -> None:
    """没配 owner_email 时仍应触发判定（监控可见），只是不发邮件。"""

    engine, maker = await _make_session()
    spy = _SpyEmailSender()
    base_now = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

    async with maker() as session:
        last = None
        for i in range(DEFAULT_THRESHOLD):
            last = await maybe_escalate(
                session,
                _payload(finding_id=i + 1),
                smtp_config=_smtp_config(),
                smtp_sender="bot@example.com",
                owner_email=None,
                now=base_now + timedelta(seconds=i),
                email_sender=spy,
            )
        await session.commit()

    assert last is not None
    assert last.triggered is True
    assert spy.calls == []
    await engine.dispose()
