"""``bootstrap_builtin_cta_patterns`` 与 5 条内置 CTA 定义的功能性测试（W11-T2）。

测试目标：

1. 启动时从空库写入全部 5 条 CTA 模式（``is_system=True``）。
2. 二次调用幂等（``unchanged == 5``）。
3. 全量 ``hardness`` 命中 :data:`KNOWN_HARDNESS`，``urgency_type`` 命中
   :data:`KNOWN_URGENCY_TYPES`。
4. 每条 CTA 至少 5 条 ``sample_phrases``（产品规范）。
5. 每条 ``description`` ≥ 80 字。
6. 5 条 CTA 的 ``urgency_type`` 互不重复，覆盖词汇表全集。

测试 DB 通过 SQLite ``:memory:`` 异步引擎构建；CTA 表无外键依赖。
"""

# pylint: disable=invalid-name

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base

# 必须 import 全部模型，确保 Base.metadata 拥有完整 schema。
import app.models.api_quota  # noqa: F401  pylint: disable=unused-import
import app.models.brand_archetype  # noqa: F401  pylint: disable=unused-import
import app.models.commerce_assets  # noqa: F401  pylint: disable=unused-import
import app.models.compliance  # noqa: F401  pylint: disable=unused-import
import app.models.cta_pattern  # noqa: F401  pylint: disable=unused-import
import app.models.hook_pattern  # noqa: F401  pylint: disable=unused-import
import app.models.llm  # noqa: F401  pylint: disable=unused-import
import app.models.story_formula  # noqa: F401  pylint: disable=unused-import
import app.models.studio  # noqa: F401  pylint: disable=unused-import
import app.models.task  # noqa: F401  pylint: disable=unused-import
import app.models.task_links  # noqa: F401  pylint: disable=unused-import

from app.models.cta_pattern import CtaPattern
from app.services.commerce.builtin_cta_patterns import (
    BUILTIN_CTA_PATTERN_DEFINITIONS,
    KNOWN_HARDNESS,
    KNOWN_URGENCY_TYPES,
    bootstrap_builtin_cta_patterns,
)


EXPECTED_CTA_IDS: frozenset[str] = frozenset(
    {
        "scarcity_cta",
        "social_proof_cta",
        "benefit_direct_cta",
        "risk_removal_cta",
        "urgency_simple_cta",
    }
)


async def _build_session() -> tuple[AsyncSession, object]:
    """构建一次性 SQLite 异步会话；cta_patterns 无外键依赖，无需 stub。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    db = session_local()
    return db, engine


@pytest.mark.asyncio
async def test_bootstrap_inserts_all_5_cta_patterns() -> None:
    """新库 -> 5 条 ``is_system=True`` 行写入；ID 集合等于约定集合。"""
    db, engine = await _build_session()
    async with db:
        stats = await bootstrap_builtin_cta_patterns(db)

        assert stats == {"inserted": 5, "updated": 0, "unchanged": 0}

        rows = (await db.execute(select(CtaPattern))).scalars().all()
        assert len(rows) == 5
        assert {row.id for row in rows} == EXPECTED_CTA_IDS
        for row in rows:
            assert row.is_system is True
    await engine.dispose()


@pytest.mark.asyncio
async def test_bootstrap_idempotent() -> None:
    """连调两次：第一次全部 inserted，第二次全部 unchanged。"""
    db, engine = await _build_session()
    async with db:
        first = await bootstrap_builtin_cta_patterns(db)
        second = await bootstrap_builtin_cta_patterns(db)

        assert first == {"inserted": 5, "updated": 0, "unchanged": 0}
        assert second == {"inserted": 0, "updated": 0, "unchanged": 5}

        rows = (await db.execute(select(CtaPattern))).scalars().all()
        assert len(rows) == 5
    await engine.dispose()


def test_hardness_and_urgency_in_known_vocabulary() -> None:
    """每条 CTA 的 ``hardness`` / ``urgency_type`` 必须命中已知词汇表。"""
    for definition in BUILTIN_CTA_PATTERN_DEFINITIONS:
        assert definition.hardness in KNOWN_HARDNESS, (
            f"cta '{definition.id}' uses unknown hardness "
            f"{definition.hardness!r}"
        )
        assert definition.urgency_type in KNOWN_URGENCY_TYPES, (
            f"cta '{definition.id}' uses unknown urgency_type "
            f"{definition.urgency_type!r}"
        )


def test_each_cta_has_at_least_5_sample_phrases() -> None:
    """每条 CTA 至少 5 条 ``sample_phrases``（运营投放需要差异化样例）。"""
    for definition in BUILTIN_CTA_PATTERN_DEFINITIONS:
        assert len(definition.sample_phrases) >= 5, (
            f"cta '{definition.id}' has only {len(definition.sample_phrases)} "
            f"sample_phrases (need >= 5)"
        )


def test_each_cta_description_is_substantial() -> None:
    """每条 ``description`` 至少 80 字，满足产品规范"~80-150 字"下限。"""
    for definition in BUILTIN_CTA_PATTERN_DEFINITIONS:
        assert len(definition.description) >= 80, (
            f"cta '{definition.id}' description only "
            f"{len(definition.description)} chars (need >= 80)"
        )


def test_urgency_types_cover_known_vocabulary() -> None:
    """5 条 CTA 的 ``urgency_type`` 不重复，覆盖 :data:`KNOWN_URGENCY_TYPES` 全集。"""
    urgency_types = [d.urgency_type for d in BUILTIN_CTA_PATTERN_DEFINITIONS]
    assert len(urgency_types) == len(set(urgency_types)), (
        f"duplicate urgency_type detected: {urgency_types}"
    )
    assert set(urgency_types) == KNOWN_URGENCY_TYPES
