"""``/api/v1/commerce/projects/{project_id}/subtitle-styles`` CRUD 路由测试（W30-T3）。

覆盖 12 个核心路径：

1. POST happy path: 合规 payload → 201 + 项目级行落地。
2. POST 不存在的 project → 404。
3. POST 同 project 同 name 冲突 → 409。
4. PATCH happy path: 修改 font_size → 200，更新落地。
5. PATCH 系统级行（project_id IS NULL）→ 403 immutable。
6. PATCH 行不属于该 project → 404。
7. PATCH rename 后与同 project name 冲突 → 409。
8. DELETE happy path: 项目级行被删 → 204。
9. DELETE 系统级行 → 403。
10. DELETE 不存在 → 404。
11. GET merged 视图: 系统级 + 项目级覆盖都返回；同名时项目级覆盖系统级。
12. GET project 不存在 → 404。
"""

# pylint: disable=invalid-name,redefined-outer-name,too-few-public-methods,protected-access

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
import app.models.subtitle  # noqa: F401  pylint: disable=unused-import
import app.models.task  # noqa: F401  pylint: disable=unused-import
import app.models.task_links  # noqa: F401  pylint: disable=unused-import
import app.models.voice_pack  # noqa: F401  pylint: disable=unused-import

from app.core.db import Base
from app.dependencies import get_db
from app.main import app
from app.models.studio_projects import Project
from app.models.subtitle import SubtitleStyle
from app.models.types import SubtitleAlignment, SubtitleFormat


def _build_system_style(
    *,
    style_id: str = "douyin_default",
    name: str = "抖音默认",
) -> SubtitleStyle:
    """构造一条 W18 系统级 seed 行。"""
    return SubtitleStyle(
        id=style_id,
        name=name,
        description="",
        language_code="zh-CN",
        format=SubtitleFormat.ass,
        font_family="Source Han Sans CN Heavy",
        font_fallback_chain=[],
        font_size=60,
        primary_colour="&H00FFFFFF",
        secondary_colour="&H00FFFFFF",
        outline_colour="&H00000000",
        back_colour="&H80000000",
        bold=True,
        italic=False,
        border_style=1,
        outline=3.0,
        shadow=1.0,
        alignment=SubtitleAlignment.bottom_center,
        margin_l=60,
        margin_r=60,
        margin_v=200,
        play_res_x=1080,
        play_res_y=1920,
        is_system=True,
        sort_order=0,
        project_id=None,
    )


async def _build_engine() -> tuple[
    async_sessionmaker[AsyncSession], AsyncEngine
]:
    """构建 in-memory SQLite + 全 schema。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", future=True
    )
    session_local = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return session_local, engine


def _make_override(session_local: async_sessionmaker[AsyncSession]):
    """与 voice_packs_custom_api 测试一致的 commit/rollback wrapper。"""

    async def _get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_local() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return _get_db


async def _seed_project_and_system_style(
    session_local: async_sessionmaker[AsyncSession],
    *,
    project_id: str = "proj-1",
) -> None:
    """种入一条 project 行 + 一条系统级 seed 行，作为多个测试的共同 baseline。"""
    async with session_local() as session:
        session.add(
            Project(
                id=project_id,
                name="Demo Project",
                description="",
                style="modern",
            )
        )
        session.add(_build_system_style())
        await session.commit()


def _create_payload(name: str = "项目大字幕") -> dict:
    """构造一个合规的 :class:`ProjectSubtitleStyleCreateInput` body。"""
    return {
        "name": name,
        "description": "项目专属字幕",
        "language_code": "zh-CN",
        "format": "ass",
        "font_family": "Source Han Sans CN Heavy",
        "font_size": 80,
        "primary_colour": "&H00FFFFFF",
        "secondary_colour": "&H00FFFFFF",
        "outline_colour": "&H00000000",
        "back_colour": "&H80000000",
        "bold": True,
        "italic": False,
        "border_style": 1,
        "outline": 3.0,
        "shadow": 1.0,
        "alignment": 2,
        "margin_l": 60,
        "margin_r": 60,
        "margin_v": 200,
        "play_res_x": 1080,
        "play_res_y": 1920,
        "font_fallback_chain": ["Source Han Sans CN Heavy", "PingFang SC"],
    }


# ---------------------------------------------------------------------------
# POST 路径
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_creates_project_subtitle_style_returns_201(
    client: TestClient,
) -> None:
    """合规 payload + 已存在 project → 201 + 项目级行落地。"""
    session_local, engine = await _build_engine()
    await _seed_project_and_system_style(session_local)
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.post(
            "/api/v1/commerce/projects/proj-1/subtitle-styles",
            json=_create_payload(),
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["data"]["name"] == "项目大字幕"
        assert body["data"]["project_id"] == "proj-1"
        assert body["data"]["is_system"] is False
        assert body["data"]["alignment"] == 2

        async with session_local() as session:
            row = await session.get(SubtitleStyle, body["data"]["id"])
            assert row is not None
            assert row.project_id == "proj-1"
            assert row.is_system is False
            assert row.font_size == 80
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_post_returns_404_when_project_missing(
    client: TestClient,
) -> None:
    """target project 不存在 → 404。"""
    session_local, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.post(
            "/api/v1/commerce/projects/no-such-project/subtitle-styles",
            json=_create_payload(),
        )
        assert res.status_code == 404, res.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_post_returns_409_on_name_conflict(
    client: TestClient,
) -> None:
    """同 project 同 name 冲突 → 409。"""
    session_local, engine = await _build_engine()
    await _seed_project_and_system_style(session_local)
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        first = client.post(
            "/api/v1/commerce/projects/proj-1/subtitle-styles",
            json=_create_payload(name="项目大字幕"),
        )
        assert first.status_code == 201

        second = client.post(
            "/api/v1/commerce/projects/proj-1/subtitle-styles",
            json=_create_payload(name="项目大字幕"),
        )
        assert second.status_code == 409, second.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


# ---------------------------------------------------------------------------
# PATCH 路径
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_updates_project_style_returns_200(
    client: TestClient,
) -> None:
    """合规 patch → 200 + 字段更新落地。"""
    session_local, engine = await _build_engine()
    await _seed_project_and_system_style(session_local)
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        post = client.post(
            "/api/v1/commerce/projects/proj-1/subtitle-styles",
            json=_create_payload(),
        )
        style_id = post.json()["data"]["id"]

        res = client.patch(
            f"/api/v1/commerce/projects/proj-1/subtitle-styles/{style_id}",
            json={"font_size": 96, "italic": True},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["data"]["font_size"] == 96
        assert body["data"]["italic"] is True
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_patch_returns_403_for_system_style(
    client: TestClient,
) -> None:
    """patch 系统级行（project_id IS NULL）→ 403 immutable。"""
    session_local, engine = await _build_engine()
    await _seed_project_and_system_style(session_local)
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.patch(
            "/api/v1/commerce/projects/proj-1/subtitle-styles/douyin_default",
            json={"font_size": 96},
        )
        assert res.status_code == 403, res.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_patch_returns_404_when_style_belongs_to_other_project(
    client: TestClient,
) -> None:
    """目标 style 属于另一个 project → 404（避免跨 project 写入）。"""
    session_local, engine = await _build_engine()
    await _seed_project_and_system_style(session_local, project_id="proj-1")
    async with session_local() as session:
        session.add(
            Project(
                id="proj-2",
                name="Other Project",
                description="",
                style="modern",
            )
        )
        await session.commit()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        post = client.post(
            "/api/v1/commerce/projects/proj-1/subtitle-styles",
            json=_create_payload(),
        )
        style_id = post.json()["data"]["id"]

        res = client.patch(
            f"/api/v1/commerce/projects/proj-2/subtitle-styles/{style_id}",
            json={"font_size": 96},
        )
        assert res.status_code == 404, res.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_patch_returns_409_on_rename_conflict(
    client: TestClient,
) -> None:
    """rename 后与同 project name 冲突 → 409。"""
    session_local, engine = await _build_engine()
    await _seed_project_and_system_style(session_local)
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        a = client.post(
            "/api/v1/commerce/projects/proj-1/subtitle-styles",
            json=_create_payload(name="样式A"),
        )
        b = client.post(
            "/api/v1/commerce/projects/proj-1/subtitle-styles",
            json=_create_payload(name="样式B"),
        )
        assert a.status_code == 201 and b.status_code == 201
        b_id = b.json()["data"]["id"]

        res = client.patch(
            f"/api/v1/commerce/projects/proj-1/subtitle-styles/{b_id}",
            json={"name": "样式A"},
        )
        assert res.status_code == 409, res.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


# ---------------------------------------------------------------------------
# DELETE 路径
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_removes_project_style_returns_200(
    client: TestClient,
) -> None:
    """delete 项目级行 → 200，DB 行真删。"""
    session_local, engine = await _build_engine()
    await _seed_project_and_system_style(session_local)
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        post = client.post(
            "/api/v1/commerce/projects/proj-1/subtitle-styles",
            json=_create_payload(),
        )
        style_id = post.json()["data"]["id"]

        res = client.delete(
            f"/api/v1/commerce/projects/proj-1/subtitle-styles/{style_id}"
        )
        assert res.status_code == 200, res.text

        async with session_local() as session:
            row = await session.get(SubtitleStyle, style_id)
            assert row is None
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_delete_returns_403_for_system_style(
    client: TestClient,
) -> None:
    """delete 系统级行 → 403。"""
    session_local, engine = await _build_engine()
    await _seed_project_and_system_style(session_local)
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.delete(
            "/api/v1/commerce/projects/proj-1/subtitle-styles/douyin_default"
        )
        assert res.status_code == 403, res.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_delete_returns_404_when_style_missing(
    client: TestClient,
) -> None:
    """delete 不存在的 style → 404。"""
    session_local, engine = await _build_engine()
    await _seed_project_and_system_style(session_local)
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.delete(
            "/api/v1/commerce/projects/proj-1/subtitle-styles/no-such-style"
        )
        assert res.status_code == 404, res.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


# ---------------------------------------------------------------------------
# GET merged 视图
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_merged_view_overrides_system_with_project(
    client: TestClient,
) -> None:
    """GET merged 视图：项目级同名行覆盖系统级，独有 name 单独列出。"""
    session_local, engine = await _build_engine()
    await _seed_project_and_system_style(session_local)
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        client.post(
            "/api/v1/commerce/projects/proj-1/subtitle-styles",
            json=_create_payload(name="抖音默认"),
        )
        client.post(
            "/api/v1/commerce/projects/proj-1/subtitle-styles",
            json=_create_payload(name="项目独有大字幕"),
        )

        res = client.get(
            "/api/v1/commerce/projects/proj-1/subtitle-styles"
        )
        assert res.status_code == 200, res.text
        items = res.json()["data"]
        names = [it["name"] for it in items]
        assert "抖音默认" in names
        assert "项目独有大字幕" in names

        douyin_entry = next(it for it in items if it["name"] == "抖音默认")
        assert douyin_entry["is_system"] is False
        assert douyin_entry["project_id"] == "proj-1"
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_merged_view_returns_404_for_missing_project(
    client: TestClient,
) -> None:
    """GET 不存在的 project → 404。"""
    session_local, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get(
            "/api/v1/commerce/projects/no-such-project/subtitle-styles"
        )
        assert res.status_code == 404, res.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()
