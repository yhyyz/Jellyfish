"""``bootstrap_builtin_brand_archetypes`` 与 12 条原型定义的功能性测试（W11-T2）。

测试目标：

1. 启动时从空库写入全部 12 条品牌人格原型（``is_system=True``）。
2. 二次调用幂等（``unchanged == 12``）。
3. 全量定义 ``id`` 都命中 :data:`KNOWN_ARCHETYPE_IDS`（与 W11-T3 枚举对齐）。
4. ``voice_traits`` ≥ 5、``sample_brands`` ∈ [3, 5]、``speech_patterns``
   同时包含 ``do`` 与 ``dont`` 且各 ≥ 5 条。
5. 每条 ``motivation`` ≥ 80 字（满足"~80-150 字"产品规范）。
6. 12 条原型 ``id`` 不重复，且覆盖 :data:`KNOWN_ARCHETYPE_IDS` 全集。
7. 每条 ``name_zh`` 不为空（中文展示必备）。
"""

# pylint: disable=invalid-name,no-member

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

from app.models.brand_archetype import BrandArchetype
from app.services.commerce.builtin_brand_archetypes import (
    BUILTIN_BRAND_ARCHETYPE_DEFINITIONS,
    KNOWN_ARCHETYPE_IDS,
    bootstrap_builtin_brand_archetypes,
)


EXPECTED_ARCHETYPE_IDS: frozenset[str] = frozenset(
    {
        "sage",
        "jester",
        "rebel",
        "provocateur",
        "maverick",
        "friend",
        "expert",
        "cheerleader",
        "storyteller",
        "analyst",
        "coach",
        "minimalist",
    }
)


async def _build_session() -> tuple[AsyncSession, object]:
    """构建一次性 SQLite 异步会话；brand_archetypes 无外键依赖，无需 stub。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    db = session_local()
    return db, engine


@pytest.mark.asyncio
async def test_bootstrap_inserts_all_12_archetypes() -> None:
    """新库 -> 12 条 ``is_system=True`` 行写入；ID 集合等于约定集合。"""
    db, engine = await _build_session()
    async with db:
        stats = await bootstrap_builtin_brand_archetypes(db)

        assert stats == {"inserted": 12, "updated": 0, "unchanged": 0}

        rows = (await db.execute(select(BrandArchetype))).scalars().all()
        assert len(rows) == 12
        assert {row.id for row in rows} == EXPECTED_ARCHETYPE_IDS
        for row in rows:
            assert row.is_system is True
    await engine.dispose()


@pytest.mark.asyncio
async def test_bootstrap_idempotent() -> None:
    """连调两次：第一次全部 inserted，第二次全部 unchanged。"""
    db, engine = await _build_session()
    async with db:
        first = await bootstrap_builtin_brand_archetypes(db)
        second = await bootstrap_builtin_brand_archetypes(db)

        assert first == {"inserted": 12, "updated": 0, "unchanged": 0}
        assert second == {"inserted": 0, "updated": 0, "unchanged": 12}

        rows = (await db.execute(select(BrandArchetype))).scalars().all()
        assert len(rows) == 12
    await engine.dispose()


def test_all_archetype_ids_in_known_vocabulary() -> None:
    """每条原型的 ``id`` 必须命中 :data:`KNOWN_ARCHETYPE_IDS`。"""
    for definition in BUILTIN_BRAND_ARCHETYPE_DEFINITIONS:
        assert definition.id in KNOWN_ARCHETYPE_IDS, (
            f"archetype uses unknown id {definition.id!r}; "
            f"allowed: {sorted(KNOWN_ARCHETYPE_IDS)}"
        )


def test_voice_traits_and_sample_brands_constraints() -> None:
    """``voice_traits`` ≥ 5、``sample_brands`` ∈ [3, 5]。

    上限来自 Pydantic 字段配置（``max_length``），下限做运行时显式断言以
    防止后续修改时把校验移除。
    """
    for definition in BUILTIN_BRAND_ARCHETYPE_DEFINITIONS:
        assert 5 <= len(definition.voice_traits) <= 10, (
            f"archetype '{definition.id}' voice_traits "
            f"{len(definition.voice_traits)} out of [5, 10]"
        )
        assert 3 <= len(definition.sample_brands) <= 5, (
            f"archetype '{definition.id}' sample_brands "
            f"{len(definition.sample_brands)} out of [3, 5]"
        )


def test_speech_patterns_have_do_and_dont() -> None:
    """``speech_patterns`` 必须同时含 ``do`` 与 ``dont`` 且各 ≥ 5 条。"""
    for definition in BUILTIN_BRAND_ARCHETYPE_DEFINITIONS:
        sp = definition.speech_patterns
        assert set(sp.keys()) == {"do", "dont"}, (
            f"archetype '{definition.id}' speech_patterns keys "
            f"{sorted(sp.keys())} != {{'do', 'dont'}}"
        )
        assert len(sp["do"]) >= 5, (
            f"archetype '{definition.id}' speech_patterns.do has only "
            f"{len(sp['do'])} entries (need >= 5)"
        )
        assert len(sp["dont"]) >= 5, (
            f"archetype '{definition.id}' speech_patterns.dont has only "
            f"{len(sp['dont'])} entries (need >= 5)"
        )


def test_each_archetype_motivation_is_substantial() -> None:
    """每条 ``motivation`` 至少 80 字，满足产品规范"~80-150 字"下限。"""
    for definition in BUILTIN_BRAND_ARCHETYPE_DEFINITIONS:
        assert len(definition.motivation) >= 80, (
            f"archetype '{definition.id}' motivation only "
            f"{len(definition.motivation)} chars (need >= 80)"
        )


def test_archetype_ids_cover_known_vocabulary() -> None:
    """12 条原型 ``id`` 不重复，且覆盖 :data:`KNOWN_ARCHETYPE_IDS` 全集。"""
    ids = [d.id for d in BUILTIN_BRAND_ARCHETYPE_DEFINITIONS]
    assert len(ids) == len(set(ids)), f"duplicate archetype id detected: {ids}"
    assert set(ids) == KNOWN_ARCHETYPE_IDS


def test_each_archetype_has_chinese_name() -> None:
    """每条原型必须有非空 ``name_zh``，前端中文展示必备。"""
    for definition in BUILTIN_BRAND_ARCHETYPE_DEFINITIONS:
        assert definition.name_zh.strip(), (
            f"archetype '{definition.id}' has empty name_zh"
        )
