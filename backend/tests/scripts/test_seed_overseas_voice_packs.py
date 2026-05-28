"""W29-T10 seed_overseas_voice_packs 脚本单元测试。

覆盖：
    1. ``--dry-run``：不调 DashScope SDK / 不写 DB；rc=0。
    2. happy path：DEPLOYING → OK，6 条 voice 全部 seed 成功；rc=0。
       VoicePack 行 6 条都 ``is_system=True`` + ``clone_status=ready``。
    3. 幂等：第 2 次跑（已存在 6 行）只 skip 不调 DashScope；rc=0。
    4. failure：mock DashScope 返回 UNDEPLOYED，部分失败；rc=1。
"""

# pylint: disable=redefined-outer-name,too-few-public-methods,protected-access

from __future__ import annotations

import argparse
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 必须 import 全部模型以确保 Base.metadata 拥有完整 schema。
import app.models.api_quota  # noqa: F401  pylint: disable=unused-import
import app.models.commerce_assets  # noqa: F401  pylint: disable=unused-import
import app.models.compliance  # noqa: F401  pylint: disable=unused-import
import app.models.llm  # noqa: F401  pylint: disable=unused-import
import app.models.story_formula  # noqa: F401  pylint: disable=unused-import
import app.models.studio  # noqa: F401  pylint: disable=unused-import
import app.models.task  # noqa: F401  pylint: disable=unused-import
import app.models.task_links  # noqa: F401  pylint: disable=unused-import
import app.models.voice_pack  # noqa: F401  pylint: disable=unused-import

from app.core.db import Base
from app.models.types import VoiceCloneStatus
from app.models.voice_pack import VoicePack
from app.services.studio import voice_clone_service
from app.services.studio.builtin_voice_packs import OVERSEAS_VOICE_SPECS

import scripts.seed_overseas_voice_packs as seed_module


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    """构造 file-backed SQLite 引擎。"""
    db_path = tmp_path / "seed-overseas.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_local = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield session_local
    await engine.dispose()


@pytest_asyncio.fixture
async def patched_session_maker(session_factory, monkeypatch):
    """让 seed_module + voice_clone_service 都看到同一个 engine。"""
    monkeypatch.setattr(seed_module, "async_session_maker", session_factory)
    return session_factory


@pytest.fixture
def stub_create_and_query(monkeypatch):
    """默认 stub：create_voice 返回固定 voice_id，query 第一次 OK。"""
    create_calls: list[dict[str, Any]] = []
    query_calls: list[str] = []

    async def _fake_create(**kwargs: Any) -> str:
        create_calls.append(kwargs)
        return f"cosyvoice-v3-plus-{kwargs['prefix']}-fake"

    async def _fake_query(*, voice_id: str, region):  # noqa: ARG001
        query_calls.append(voice_id)
        return VoiceCloneStatus.ready, None

    monkeypatch.setattr(seed_module, "create_voice_remote", _fake_create)
    monkeypatch.setattr(seed_module, "query_clone_status", _fake_query)

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(seed_module.asyncio, "sleep", _no_sleep)

    return {"create_calls": create_calls, "query_calls": query_calls}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_overseas_voice_specs_count_and_languages() -> None:
    """OVERSEAS_VOICE_SPECS 必须包含 6 条 en/ja/ko 各 2。"""
    assert len(OVERSEAS_VOICE_SPECS) == 6
    by_lang = {}
    for spec in OVERSEAS_VOICE_SPECS:
        by_lang.setdefault(spec.language_code, []).append(spec)
    assert sorted(by_lang.keys()) == ["en-US", "ja-JP", "ko-KR"]
    for lang_specs in by_lang.values():
        assert len(lang_specs) == 2


@pytest.mark.asyncio
async def test_dry_run_does_not_call_dashscope(
    session_factory,
    patched_session_maker,
    stub_create_and_query,
):
    """--dry-run 下不调 SDK / 不写 DB。"""
    args = argparse.Namespace(
        sample_url="https://example/sample.wav",
        dry_run=True,
        max_poll_attempts=5,
        poll_interval_sec=0.0,
    )
    rc = await seed_module._run(args)
    assert rc == 0
    assert stub_create_and_query["create_calls"] == []

    async with session_factory() as session:
        from sqlalchemy import select

        rows = (
            await session.execute(
                select(VoicePack).where(VoicePack.is_system.is_(True))
            )
        ).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_seed_happy_path_all_six(
    session_factory,
    patched_session_maker,
    stub_create_and_query,
):
    """全部 6 条 ready 路径：DB 行落库 + create 调用 6 次。"""
    args = argparse.Namespace(
        sample_url="https://example/sample.wav",
        dry_run=False,
        max_poll_attempts=5,
        poll_interval_sec=0.0,
    )
    rc = await seed_module._run(args)
    assert rc == 0

    assert len(stub_create_and_query["create_calls"]) == 6
    async with session_factory() as session:
        from sqlalchemy import select

        rows = (
            await session.execute(
                select(VoicePack).where(VoicePack.is_system.is_(True))
            )
        ).scalars().all()
        assert len(rows) == 6
        for row in rows:
            assert row.clone_status == VoiceCloneStatus.ready
            assert row.cloned_at is not None
            assert row.target_model == "cosyvoice-v3-plus"


@pytest.mark.asyncio
async def test_seed_idempotent_skips_existing(
    session_factory,
    patched_session_maker,
    stub_create_and_query,
):
    """跑两次 seed：第 2 次 create_voice 不应被再次调用。"""
    args = argparse.Namespace(
        sample_url="https://example/sample.wav",
        dry_run=False,
        max_poll_attempts=5,
        poll_interval_sec=0.0,
    )
    rc1 = await seed_module._run(args)
    assert rc1 == 0
    first_calls = len(stub_create_and_query["create_calls"])
    assert first_calls == 6

    rc2 = await seed_module._run(args)
    assert rc2 == 0
    assert len(stub_create_and_query["create_calls"]) == first_calls


@pytest.mark.asyncio
async def test_seed_returns_rc_1_on_failure(
    session_factory,
    patched_session_maker,
    monkeypatch,
):
    """有 voice 训练失败时 rc=1。"""

    async def _fake_create(**kwargs: Any) -> str:  # noqa: ARG001
        return f"cosyvoice-v3-plus-{kwargs['prefix']}-fake"

    async def _fake_query(*, voice_id: str, region):  # noqa: ARG001
        return VoiceCloneStatus.failed, "DashScope returned UNDEPLOYED"

    monkeypatch.setattr(seed_module, "create_voice_remote", _fake_create)
    monkeypatch.setattr(seed_module, "query_clone_status", _fake_query)

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(seed_module.asyncio, "sleep", _no_sleep)

    args = argparse.Namespace(
        sample_url="https://example/sample.wav",
        dry_run=False,
        max_poll_attempts=2,
        poll_interval_sec=0.0,
    )
    rc = await seed_module._run(args)
    assert rc == 1


def test_voice_clone_service_helpers_exposed() -> None:
    """voice_clone_service 必须暴露 utcnow_naive 与 create_voice_remote 等公共 API。"""
    assert hasattr(voice_clone_service, "create_voice_remote")
    assert hasattr(voice_clone_service, "query_clone_status")
    assert hasattr(voice_clone_service, "utcnow_naive")
