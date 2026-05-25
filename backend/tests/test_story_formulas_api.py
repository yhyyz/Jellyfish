"""``/api/v1/studio/story-formulas`` 只读接口测试（W6-T2，W14 更新）。

测试范围：

- list 默认返回 12 条（6 cn + 6 global，与 ``bootstrap_builtin_story_formulas`` 一致）。
- list 按 ``region=cn`` 返回 6 条 cn 内置公式。
- list 按 ``region=global`` 返回 6 条国际经典叙事公式（W11-T1 新增）。
- list 按 ``category=cn_workplace`` 只剩 1 条（``workplace_hero``）。
- detail 不存在的 ID -> 404。
- detail 存在 ID 返回完整结构（含 ``structure.beats``）。
- list 默认按 ``sort_order`` 升序输出。

W11-T1 引入了 6 条 ``region=global`` 的国际叙事公式（Hero's Journey、Pixar
Story Spine、Three-Act、SCQA、StoryBrand SB7、PAS/BAB），因此默认 list
长度由 6 变为 12，本文件相关断言已同步更新。

测试基于内存 SQLite + ``app.dependency_overrides[get_db]``，并预先写入
``story_formula_generator_v1`` 占位 PromptTemplate，以满足
``story_formulas.prompt_template_id`` 外键约束。
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
import app.models.commerce_assets  # noqa: F401  pylint: disable=unused-import
import app.models.compliance  # noqa: F401  pylint: disable=unused-import
import app.models.llm  # noqa: F401  pylint: disable=unused-import
import app.models.story_formula  # noqa: F401  pylint: disable=unused-import
import app.models.studio  # noqa: F401  pylint: disable=unused-import
import app.models.task  # noqa: F401  pylint: disable=unused-import
import app.models.task_links  # noqa: F401  pylint: disable=unused-import

from app.core.db import Base
from app.dependencies import get_db
from app.main import app
from app.models.studio_prompts_files_timeline import PromptTemplate
from app.models.types import PromptCategory
from app.services.commerce.builtin_story_formulas import (
    BUILTIN_FORMULA_PROMPT_TEMPLATE_ID,
    bootstrap_builtin_story_formulas,
)


async def _build_engine_with_formulas() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
    """构建一次性 SQLite 引擎并写入 12 条系统公式（6 cn + 6 global）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_local() as seed_session:
        seed_session.add(
            PromptTemplate(
                id=BUILTIN_FORMULA_PROMPT_TEMPLATE_ID,
                category=PromptCategory.story_formula_generator,
                name="stub-template-for-test",
                preview="",
                content="",
                variables=[],
                is_default=False,
                is_system=True,
            )
        )
        await seed_session.commit()
        await bootstrap_builtin_story_formulas(seed_session)
    return session_local, engine


def _make_override(session_local: async_sessionmaker[AsyncSession]):
    """构造 dependency override：每次请求复用同一个 sessionmaker。"""

    async def _get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_local() as session:
            yield session

    return _get_db


@pytest.mark.asyncio
async def test_list_returns_all_twelve_formulas(client: TestClient) -> None:
    """默认 list 返回全部 12 条系统公式（6 cn + 6 global）。"""
    session_local, engine = await _build_engine_with_formulas()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get("/api/v1/studio/story-formulas")
        assert res.status_code == 200
        body = res.json()
        assert body["code"] == 200
        items = body["data"]
        assert len(items) == 12
        ids = {item["id"] for item in items}
        assert ids == {
            # 6 条 cn 内置公式（W3-T2 锁定）
            "underdog_triumph",
            "contrast_surprise",
            "workplace_hero",
            "family_conflict",
            "mystery_twist",
            "time_travel",
            # 6 条 global 国际叙事公式（W11-T1 新增）
            "heros_journey",
            "pixar_story_spine",
            "three_act",
            "scqa",
            "storybrand_sb7",
            "pas_bab",
        }
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_filtered_by_region_cn(client: TestClient) -> None:
    """region=cn 过滤后返回 6 条 cn 内置公式。"""
    session_local, engine = await _build_engine_with_formulas()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get("/api/v1/studio/story-formulas", params={"region": "cn"})
        assert res.status_code == 200
        items = res.json()["data"]
        assert len(items) == 6
        assert all(item["region"] == "cn" for item in items)
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_filtered_by_region_global(client: TestClient) -> None:
    """region=global 过滤后返回 W11-T1 新增的 6 条国际叙事公式。"""
    session_local, engine = await _build_engine_with_formulas()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get("/api/v1/studio/story-formulas", params={"region": "global"})
        assert res.status_code == 200
        items = res.json()["data"]
        assert len(items) == 6
        assert all(item["region"] == "global" for item in items)
        ids = {item["id"] for item in items}
        assert ids == {
            "heros_journey",
            "pixar_story_spine",
            "three_act",
            "scqa",
            "storybrand_sb7",
            "pas_bab",
        }
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_filtered_by_category_cn_workplace(client: TestClient) -> None:
    """category=cn_workplace 仅命中 ``workplace_hero``。"""
    session_local, engine = await _build_engine_with_formulas()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get(
            "/api/v1/studio/story-formulas",
            params={"category": "cn_workplace"},
        )
        assert res.status_code == 200
        items = res.json()["data"]
        assert len(items) == 1
        assert items[0]["id"] == "workplace_hero"
        assert items[0]["category"] == "cn_workplace"
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_detail_returns_404_for_unknown_id(client: TestClient) -> None:
    """detail 不存在 ID 返回 404。"""
    session_local, engine = await _build_engine_with_formulas()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get("/api/v1/studio/story-formulas/__missing__")
        assert res.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_detail_returns_full_structure(client: TestClient) -> None:
    """detail 返回完整字段，含 ``structure.beats`` 嵌套结构。"""
    session_local, engine = await _build_engine_with_formulas()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get("/api/v1/studio/story-formulas/underdog_triumph")
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["id"] == "underdog_triumph"
        assert data["is_system"] is True
        assert data["region"] == "cn"
        assert isinstance(data["structure"], dict)
        beats = data["structure"]["beats"]
        assert isinstance(beats, list) and len(beats) >= 1
        assert {"id", "duration_sec", "function", "shot_type"} <= set(beats[0])
        assert isinstance(data["risk_flags"], list)
        assert isinstance(data["use_cases"], list)
        assert isinstance(data["avoid_cases"], list)
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_ordered_by_sort_order_asc(client: TestClient) -> None:
    """list 默认按 ``sort_order`` 升序输出。"""
    session_local, engine = await _build_engine_with_formulas()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get("/api/v1/studio/story-formulas")
        assert res.status_code == 200
        items = res.json()["data"]
        sort_orders = [item["sort_order"] for item in items]
        assert sort_orders == sorted(sort_orders)
        assert items[0]["id"] == "underdog_triumph"
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()
