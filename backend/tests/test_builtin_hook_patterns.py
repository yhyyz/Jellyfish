"""``bootstrap_builtin_hook_patterns`` 与 10 条内置钩子定义的功能性测试（W11-T2）。

测试目标：

1. 启动时从空库写入全部 10 条钩子模式（``is_system=True``）。
2. 二次调用幂等（``unchanged == 10``）。
3. 全量定义的 ``pattern_type`` 都在已知词汇表 :data:`KNOWN_PATTERN_TYPES` 中。
4. 全量定义至少 3 条 ``avoid_cases``（合规自保 baseline）。
5. 每个钩子 ``description`` ≥ 80 字（满足"~80-150 字"产品规范）。
6. ``pattern_type`` 在 10 条钩子中互不重复（每种类型各 1 条）。

测试 DB 通过 SQLite ``:memory:`` 异步引擎构建，与项目其它 service 测试保持
一致；钩子表无外键依赖，因此无需任何前置 stub。
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

from app.models.hook_pattern import HookPattern
from app.services.commerce.builtin_hook_patterns import (
    BUILTIN_HOOK_PATTERN_DEFINITIONS,
    KNOWN_PATTERN_TYPES,
    bootstrap_builtin_hook_patterns,
)


EXPECTED_HOOK_IDS: frozenset[str] = frozenset(
    {
        "question_hook",
        "conflict_hook",
        "contrast_hook",
        "numerical_hook",
        "curiosity_hook",
        "shock_hook",
        "relatable_hook",
        "dialogue_hook",
        "visual_hook",
        "pov_hook",
    }
)


async def _build_session() -> tuple[AsyncSession, object]:
    """构建一次性 SQLite 异步会话；hook_patterns 无外键依赖，无需 stub。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    db = session_local()
    return db, engine


@pytest.mark.asyncio
async def test_bootstrap_inserts_all_10_hook_patterns() -> None:
    """新库 -> 10 条 ``is_system=True`` 行写入；ID 集合等于约定集合。"""
    db, engine = await _build_session()
    async with db:
        stats = await bootstrap_builtin_hook_patterns(db)

        assert stats == {"inserted": 10, "updated": 0, "unchanged": 0}

        rows = (await db.execute(select(HookPattern))).scalars().all()
        assert len(rows) == 10
        assert {row.id for row in rows} == EXPECTED_HOOK_IDS
        for row in rows:
            assert row.is_system is True
    await engine.dispose()


@pytest.mark.asyncio
async def test_bootstrap_idempotent() -> None:
    """连调两次：第一次全部 inserted，第二次全部 unchanged。"""
    db, engine = await _build_session()
    async with db:
        first = await bootstrap_builtin_hook_patterns(db)
        second = await bootstrap_builtin_hook_patterns(db)

        assert first == {"inserted": 10, "updated": 0, "unchanged": 0}
        assert second == {"inserted": 0, "updated": 0, "unchanged": 10}

        rows = (await db.execute(select(HookPattern))).scalars().all()
        assert len(rows) == 10
    await engine.dispose()


def test_all_pattern_types_in_known_vocabulary() -> None:
    """每条钩子的 ``pattern_type`` 必须命中 :data:`KNOWN_PATTERN_TYPES`。"""
    for definition in BUILTIN_HOOK_PATTERN_DEFINITIONS:
        assert definition.pattern_type in KNOWN_PATTERN_TYPES, (
            f"hook '{definition.id}' uses unknown pattern_type "
            f"{definition.pattern_type!r}"
        )


def test_each_hook_has_at_least_three_avoid_cases() -> None:
    """每条钩子至少 3 条 ``avoid_cases``，作为合规自保 baseline。"""
    for definition in BUILTIN_HOOK_PATTERN_DEFINITIONS:
        assert len(definition.avoid_cases) >= 3, (
            f"hook '{definition.id}' has only {len(definition.avoid_cases)} "
            f"avoid_cases (need >= 3)"
        )


def test_each_hook_description_is_substantial() -> None:
    """每条 ``description`` 至少 80 字，满足产品规范"~80-150 字"下限。"""
    for definition in BUILTIN_HOOK_PATTERN_DEFINITIONS:
        assert len(definition.description) >= 80, (
            f"hook '{definition.id}' description only "
            f"{len(definition.description)} chars (need >= 80)"
        )


def test_pattern_types_are_unique_across_hooks() -> None:
    """10 条钩子 pattern_type 不重复，每种类型各 1 条（覆盖完整词汇表）。"""
    types = [definition.pattern_type for definition in BUILTIN_HOOK_PATTERN_DEFINITIONS]
    assert len(types) == len(set(types)), (
        f"duplicate pattern_type detected: {types}"
    )
    # 同时校验完整覆盖：10 种类型 == KNOWN_PATTERN_TYPES。
    assert set(types) == KNOWN_PATTERN_TYPES
