"""``/api/v1/studio/story-projects`` 接口测试（W6-T2）。

测试范围（≥10 用例）：

1. create 持久化 Project + CommerceStoryConfig 单事务。
2. create 强制 ``kind=commerce_story``（即使客户端未传也注入）。
3. list 仅返回 ``kind=commerce_story`` 项目（drama 项目被过滤）。
4. detail 不存在的项目 -> 404。
5. detail 联表读出 config。
6. patch_config 仅更新 config 字段，不触碰 Project 核心字段。
7. patch_config 项目缺失 -> 404。
8. link_product 创建 ProjectProductLink。
9. link_product 重复挂载触发 UNIQUE -> 409。
10. unlink_product 删除挂载。
11. unlink_product 挂载缺失 -> 404。
"""

# pylint: disable=invalid-name

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
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
from app.models.commerce_assets import CommerceStoryConfig, Product, ProjectProductLink
from app.models.studio import Project
from app.models.types import ProjectKind, ProjectStyle, ProjectVisualStyle


async def _build_engine() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
    """构建一次性 SQLite 引擎并返回 sessionmaker 与 engine。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return session_local, engine


async def _seed_drama_project(
    session_local: async_sessionmaker[AsyncSession],
    project_id: str = "proj_drama",
) -> None:
    """写入一条 drama 项目，用于验证 list 不返回它。"""
    async with session_local() as session:
        session.add(
            Project(
                id=project_id,
                name="普通短剧",
                description="",
                style=ProjectStyle.real_people_city,
                visual_style=ProjectVisualStyle.live_action,
                seed=0,
                kind=ProjectKind.drama.value,
                unify_style=True,
                progress=0,
                stats={},
            )
        )
        await session.commit()


async def _seed_product(
    session_local: async_sessionmaker[AsyncSession],
    product_id: str = "prod_1",
) -> None:
    """写入一条 Product 用于挂载测试。"""
    async with session_local() as session:
        session.add(
            Product(
                id=product_id,
                name=f"商品-{product_id}",
            )
        )
        await session.commit()


def _make_override(session_local: async_sessionmaker[AsyncSession]):
    """每次请求新建 session；commit 行为交给 ``get_db`` 的语义处理。"""

    async def _get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_local() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return _get_db


def _create_payload(
    project_id: str = "sp_1",
    *,
    name: str = "带货项目-1",
    formula_id: str | None = None,
) -> dict[str, object]:
    """组装一个最小可用的 create body（保证字段满足 schema 校验）。"""
    return {
        "id": project_id,
        "name": name,
        "description": "测试用",
        "style": ProjectStyle.real_people_city.value,
        "visual_style": ProjectVisualStyle.live_action.value,
        "seed": 1,
        "unify_style": True,
        "progress": 0,
        "default_video_ratio": None,
        "stats": {},
        "config": {
            "target_platform": "douyin",
            "target_duration_sec": 60,
            "formula_id": formula_id,
            "archetype": None,
            "tone_grid": {},
            "audience_override": None,
            "compliance_region": "cn_mainland",
            "compliance_profile_id": "cn_mainland_default",
            "target_kpi": "conversion",
        },
    }


@pytest.mark.asyncio
async def test_create_persists_project_and_config(client: TestClient) -> None:
    """create 后 Project + CommerceStoryConfig 同时存在。"""
    session_local, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.post(
            "/api/v1/studio/story-projects",
            json=_create_payload(),
        )
        assert res.status_code == 201
        body = res.json()
        assert body["data"]["id"] == "sp_1"
        assert body["data"]["kind"] == ProjectKind.commerce_story.value
        assert body["data"]["config"]["target_kpi"] == "conversion"

        async with session_local() as session:
            proj = await session.get(Project, "sp_1")
            cfg = await session.get(CommerceStoryConfig, "sp_1")
            assert proj is not None
            assert cfg is not None
            assert cfg.target_duration_sec == 60
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_enforces_commerce_story_kind(client: TestClient) -> None:
    """即使客户端不传 kind，服务端也会强制写入 commerce_story。"""
    session_local, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        payload = _create_payload(project_id="sp_kind")
        res = client.post("/api/v1/studio/story-projects", json=payload)
        assert res.status_code == 201
        async with session_local() as session:
            proj = await session.get(Project, "sp_kind")
            assert proj is not None
            assert proj.kind == ProjectKind.commerce_story.value
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_returns_only_commerce_story(client: TestClient) -> None:
    """list 只返回 commerce_story 项目，不返回 drama。"""
    session_local, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        await _seed_drama_project(session_local, project_id="proj_drama")
        client.post("/api/v1/studio/story-projects", json=_create_payload("sp_a"))
        client.post("/api/v1/studio/story-projects", json=_create_payload("sp_b"))
        res = client.get("/api/v1/studio/story-projects")
        assert res.status_code == 200
        ids = {item["id"] for item in res.json()["data"]}
        assert ids == {"sp_a", "sp_b"}
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_detail_returns_404_for_missing_project(client: TestClient) -> None:
    """detail 项目不存在 -> 404。"""
    session_local, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get("/api/v1/studio/story-projects/missing")
        assert res.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_detail_joins_config(client: TestClient) -> None:
    """detail 联表读出 config。"""
    session_local, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        client.post("/api/v1/studio/story-projects", json=_create_payload("sp_d"))
        res = client.get("/api/v1/studio/story-projects/sp_d")
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["config"]["compliance_profile_id"] == "cn_mainland_default"
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_patch_config_updates_only_config_fields(client: TestClient) -> None:
    """patch_config 只更新 config，不动 Project 核心字段（name 保持不变）。"""
    session_local, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        client.post("/api/v1/studio/story-projects", json=_create_payload("sp_p", name="原名"))
        res = client.patch(
            "/api/v1/studio/story-projects/sp_p/config",
            json={"target_duration_sec": 90, "target_kpi": "awareness"},
        )
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["config"]["target_duration_sec"] == 90
        assert data["config"]["target_kpi"] == "awareness"
        assert data["name"] == "原名"
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_patch_config_404_for_missing_project(client: TestClient) -> None:
    """patch_config 项目不存在 -> 404。"""
    session_local, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.patch(
            "/api/v1/studio/story-projects/missing/config",
            json={"target_duration_sec": 30},
        )
        assert res.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_link_product_creates_link(client: TestClient) -> None:
    """link_product 写入一条 ProjectProductLink。"""
    session_local, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        client.post("/api/v1/studio/story-projects", json=_create_payload("sp_l"))
        await _seed_product(session_local, "prod_x")
        res = client.post(
            "/api/v1/studio/story-projects/sp_l/products/prod_x",
            json={
                "role_in_story": "savior",
                "appearance_timing": "middle",
                "appearance_duration_sec": 8,
            },
        )
        assert res.status_code == 201
        async with session_local() as session:
            stmt = select(ProjectProductLink).where(
                ProjectProductLink.project_id == "sp_l",
                ProjectProductLink.product_id == "prod_x",
            )
            link = (await session.execute(stmt)).scalar_one_or_none()
            assert link is not None
            assert link.appearance_duration_sec == 8
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_link_product_409_on_duplicate(client: TestClient) -> None:
    """重复挂载触发 UNIQUE 约束 -> 409。"""
    session_local, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        client.post("/api/v1/studio/story-projects", json=_create_payload("sp_dup"))
        await _seed_product(session_local, "prod_d")
        first = client.post(
            "/api/v1/studio/story-projects/sp_dup/products/prod_d",
            json={
                "role_in_story": "savior",
                "appearance_timing": "middle",
                "appearance_duration_sec": 5,
            },
        )
        assert first.status_code == 201
        again = client.post(
            "/api/v1/studio/story-projects/sp_dup/products/prod_d",
            json={
                "role_in_story": "catalyst",
                "appearance_timing": "climax",
                "appearance_duration_sec": 7,
            },
        )
        assert again.status_code == 409
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_unlink_product_deletes_link(client: TestClient) -> None:
    """unlink_product 删除已存在的挂载。"""
    session_local, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        client.post("/api/v1/studio/story-projects", json=_create_payload("sp_u"))
        await _seed_product(session_local, "prod_u")
        client.post(
            "/api/v1/studio/story-projects/sp_u/products/prod_u",
            json={
                "role_in_story": "savior",
                "appearance_timing": "middle",
                "appearance_duration_sec": 5,
            },
        )
        res = client.delete("/api/v1/studio/story-projects/sp_u/products/prod_u")
        assert res.status_code == 200
        async with session_local() as session:
            stmt = select(ProjectProductLink).where(
                ProjectProductLink.project_id == "sp_u",
                ProjectProductLink.product_id == "prod_u",
            )
            assert (await session.execute(stmt)).scalar_one_or_none() is None
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_unlink_product_404_when_missing(client: TestClient) -> None:
    """unlink_product 没有匹配的挂载 -> 404。"""
    session_local, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        client.post("/api/v1/studio/story-projects", json=_create_payload("sp_n"))
        await _seed_product(session_local, "prod_n")
        res = client.delete("/api/v1/studio/story-projects/sp_n/products/prod_n")
        assert res.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()
