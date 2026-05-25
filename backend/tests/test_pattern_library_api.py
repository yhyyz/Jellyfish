"""Pattern library 只读接口测试（W14-T4）。

测试范围（≥15 用例）：

HookPattern：
  - list 默认返回 10 条
  - list 按 ``pattern_type=question`` 仅返回 1 条
  - list 按 ``pattern_type`` 未命中返回空数组
  - list 默认 ``sort_order`` 升序
  - detail 命中返回完整字段（含 ``use_cases`` / ``avoid_cases``）
  - detail 未知 ID -> 404
  - 响应壳为 ApiResponse[list/dict]

CtaPattern：
  - list 默认返回 5 条
  - list 按 ``hardness=hard`` 过滤为子集
  - list 按 ``urgency_type=scarcity`` 过滤为子集
  - detail 命中返回完整字段（含 ``sample_phrases``）
  - detail 未知 ID -> 404

BrandArchetype：
  - list 默认返回 12 条
  - list 默认 ``sort_order`` 升序
  - detail 命中返回完整字段（含 ``voice_traits`` / ``speech_patterns``）
  - detail 未知 ID -> 404

测试基于内存 SQLite + ``app.dependency_overrides[get_db]``，并使用
W11-T2 提供的 ``bootstrap_builtin_*`` 函数预填三张注册表。
"""

# pylint: disable=invalid-name

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

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

from app.core.db import Base
from app.dependencies import get_db
from app.main import app
from app.services.commerce.builtin_brand_archetypes import (
    bootstrap_builtin_brand_archetypes,
)
from app.services.commerce.builtin_cta_patterns import (
    bootstrap_builtin_cta_patterns,
)
from app.services.commerce.builtin_hook_patterns import (
    bootstrap_builtin_hook_patterns,
)


async def _build_engine_with_patterns() -> tuple[
    async_sessionmaker[AsyncSession], AsyncEngine
]:
    """构建一次性 SQLite 引擎并写入 10 钩子 + 5 CTA + 12 原型。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_local() as seed_session:
        await bootstrap_builtin_hook_patterns(seed_session)
        await bootstrap_builtin_cta_patterns(seed_session)
        await bootstrap_builtin_brand_archetypes(seed_session)
    return session_local, engine


def _make_override(session_local: async_sessionmaker[AsyncSession]):
    """构造 dependency override：每次请求复用同一个 sessionmaker。"""

    async def _get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_local() as session:
            yield session

    return _get_db


# =====================================================================
# HookPattern
# =====================================================================


@pytest.mark.asyncio
async def test_list_hook_patterns_returns_all_ten(client: TestClient) -> None:
    """list 默认返回全部 10 条钩子。"""
    session_local, engine = await _build_engine_with_patterns()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get("/api/v1/studio/hook-patterns")
        assert res.status_code == 200
        body = res.json()
        assert body["code"] == 200
        items = body["data"]
        assert len(items) == 10
        ids = {item["id"] for item in items}
        assert ids == {
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
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_hook_patterns_filtered_by_pattern_type(
    client: TestClient,
) -> None:
    """``pattern_type=question`` 仅命中 ``question_hook``。"""
    session_local, engine = await _build_engine_with_patterns()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get(
            "/api/v1/studio/hook-patterns",
            params={"pattern_type": "question"},
        )
        assert res.status_code == 200
        items = res.json()["data"]
        assert len(items) == 1
        assert items[0]["id"] == "question_hook"
        assert items[0]["pattern_type"] == "question"
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_hook_patterns_filter_unknown_returns_empty(
    client: TestClient,
) -> None:
    """``pattern_type`` 未命中任何记录时返回空数组。"""
    session_local, engine = await _build_engine_with_patterns()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get(
            "/api/v1/studio/hook-patterns",
            params={"pattern_type": "__missing__"},
        )
        assert res.status_code == 200
        assert res.json()["data"] == []
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_hook_patterns_ordered_by_sort_order_asc(
    client: TestClient,
) -> None:
    """list 默认按 ``sort_order`` 升序输出。"""
    session_local, engine = await _build_engine_with_patterns()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get("/api/v1/studio/hook-patterns")
        assert res.status_code == 200
        items = res.json()["data"]
        sort_orders = [item["sort_order"] for item in items]
        assert sort_orders == sorted(sort_orders)
        assert items[0]["id"] == "question_hook"
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_hook_pattern_returns_full_record(client: TestClient) -> None:
    """detail 返回完整字段。"""
    session_local, engine = await _build_engine_with_patterns()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get("/api/v1/studio/hook-patterns/question_hook")
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["id"] == "question_hook"
        assert data["pattern_type"] == "question"
        assert data["is_system"] is True
        assert isinstance(data["use_cases"], list) and len(data["use_cases"]) >= 1
        assert isinstance(data["avoid_cases"], list) and len(data["avoid_cases"]) >= 1
        assert data["template_text"]
        assert data["psychology"]
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_hook_pattern_unknown_returns_404(client: TestClient) -> None:
    """detail 不存在 ID 返回 404。"""
    session_local, engine = await _build_engine_with_patterns()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get("/api/v1/studio/hook-patterns/__missing__")
        assert res.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


# =====================================================================
# CtaPattern
# =====================================================================


@pytest.mark.asyncio
async def test_list_cta_patterns_returns_all_five(client: TestClient) -> None:
    """list 默认返回全部 5 条 CTA。"""
    session_local, engine = await _build_engine_with_patterns()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get("/api/v1/studio/cta-patterns")
        assert res.status_code == 200
        body = res.json()
        assert body["code"] == 200
        items = body["data"]
        assert len(items) == 5
        ids = {item["id"] for item in items}
        assert ids == {
            "scarcity_cta",
            "social_proof_cta",
            "benefit_direct_cta",
            "risk_removal_cta",
            "urgency_simple_cta",
        }
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_cta_patterns_filtered_by_hardness(client: TestClient) -> None:
    """``hardness=hard`` 仅返回硬度为 hard 的子集。"""
    session_local, engine = await _build_engine_with_patterns()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get(
            "/api/v1/studio/cta-patterns",
            params={"hardness": "hard"},
        )
        assert res.status_code == 200
        items = res.json()["data"]
        assert len(items) >= 1
        assert all(item["hardness"] == "hard" for item in items)
        assert "scarcity_cta" in {item["id"] for item in items}
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_cta_patterns_filtered_by_urgency_type(
    client: TestClient,
) -> None:
    """``urgency_type=scarcity`` 仅命中 ``scarcity_cta``。"""
    session_local, engine = await _build_engine_with_patterns()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get(
            "/api/v1/studio/cta-patterns",
            params={"urgency_type": "scarcity"},
        )
        assert res.status_code == 200
        items = res.json()["data"]
        assert len(items) == 1
        assert items[0]["id"] == "scarcity_cta"
        assert items[0]["urgency_type"] == "scarcity"
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_cta_pattern_returns_full_record(client: TestClient) -> None:
    """detail 返回完整字段，含 ``sample_phrases``。"""
    session_local, engine = await _build_engine_with_patterns()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get("/api/v1/studio/cta-patterns/scarcity_cta")
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["id"] == "scarcity_cta"
        assert data["hardness"] == "hard"
        assert data["urgency_type"] == "scarcity"
        assert data["is_system"] is True
        assert isinstance(data["sample_phrases"], list)
        assert len(data["sample_phrases"]) >= 5
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_cta_pattern_unknown_returns_404(client: TestClient) -> None:
    """detail 不存在 ID 返回 404。"""
    session_local, engine = await _build_engine_with_patterns()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get("/api/v1/studio/cta-patterns/__missing__")
        assert res.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


# =====================================================================
# BrandArchetype
# =====================================================================


@pytest.mark.asyncio
async def test_list_brand_archetypes_returns_all_twelve(
    client: TestClient,
) -> None:
    """list 默认返回全部 12 条原型。"""
    session_local, engine = await _build_engine_with_patterns()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get("/api/v1/studio/brand-archetypes")
        assert res.status_code == 200
        body = res.json()
        assert body["code"] == 200
        items = body["data"]
        assert len(items) == 12
        ids = {item["id"] for item in items}
        assert ids == {
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
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_brand_archetypes_ordered_by_sort_order_asc(
    client: TestClient,
) -> None:
    """list 默认按 ``sort_order`` 升序输出。"""
    session_local, engine = await _build_engine_with_patterns()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get("/api/v1/studio/brand-archetypes")
        assert res.status_code == 200
        items = res.json()["data"]
        sort_orders = [item["sort_order"] for item in items]
        assert sort_orders == sorted(sort_orders)
        assert items[0]["id"] == "sage"
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_brand_archetype_returns_full_record(
    client: TestClient,
) -> None:
    """detail 返回完整字段，含 voice_traits / speech_patterns / sample_brands。"""
    session_local, engine = await _build_engine_with_patterns()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get("/api/v1/studio/brand-archetypes/sage")
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["id"] == "sage"
        assert data["name"] == "Sage"
        assert data["name_zh"] == "智者"
        assert data["is_system"] is True
        assert isinstance(data["voice_traits"], dict)
        assert isinstance(data["speech_patterns"], dict)
        assert "do" in data["speech_patterns"]
        assert "dont" in data["speech_patterns"]
        assert isinstance(data["sample_brands"], list)
        assert len(data["sample_brands"]) >= 3
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_brand_archetype_unknown_returns_404(
    client: TestClient,
) -> None:
    """detail 不存在 ID 返回 404。"""
    session_local, engine = await _build_engine_with_patterns()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get("/api/v1/studio/brand-archetypes/__missing__")
        assert res.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


# =====================================================================
# 响应壳一致性
# =====================================================================


@pytest.mark.asyncio
async def test_response_envelope_is_api_response(client: TestClient) -> None:
    """三类列表/详情接口都返回 ApiResponse 形状（code/message/data）。"""
    session_local, engine = await _build_engine_with_patterns()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        for path in (
            "/api/v1/studio/hook-patterns",
            "/api/v1/studio/cta-patterns",
            "/api/v1/studio/brand-archetypes",
            "/api/v1/studio/hook-patterns/question_hook",
            "/api/v1/studio/cta-patterns/scarcity_cta",
            "/api/v1/studio/brand-archetypes/sage",
        ):
            res = client.get(path)
            assert res.status_code == 200, path
            body = res.json()
            assert set(body.keys()) >= {"code", "message", "data"}, path
            assert body["code"] == 200, path
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()
