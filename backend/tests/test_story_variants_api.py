"""``/api/v1/studio/story-variants`` 接口测试（W6-T2）。

测试范围（≥8 用例）：

1. create 写入 ``status=draft`` + ``compliance_score=0`` 的变体。
2. create 必填校验：缺 project_id / chapter_id / formula_id 应返回 422。
3. create 自动生成 id（``uuid4().hex``，与请求体无关）。
4. list 按 ``project_id`` 过滤命中。
5. list 按 ``created_at desc`` 排序。
6. list 空集合返回 200 + 空数组。
7. create 422 on bad input（formula_id 为空字符串触发 ``min_length=1``）。
8. create 服务端忽略客户端伪造的 ``status=ready``（不可绕过 draft 默认）。
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
from app.models.studio import Chapter, ChapterStatus, Project, ProjectStyle, ProjectVisualStyle
from app.models.studio_prompts_files_timeline import PromptTemplate
from app.models.types import ProjectKind, PromptCategory
from app.services.commerce.builtin_story_formulas import (
    BUILTIN_FORMULA_PROMPT_TEMPLATE_ID,
    bootstrap_builtin_story_formulas,
)


async def _build_engine_with_fixtures() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
    """构建一次性 SQLite 引擎并写入 Project + Chapter + StoryFormula。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_local() as session:
        session.add(
            PromptTemplate(
                id=BUILTIN_FORMULA_PROMPT_TEMPLATE_ID,
                category=PromptCategory.story_formula_generator,
                name="stub",
                preview="",
                content="",
                variables=[],
                is_default=False,
                is_system=True,
            )
        )
        session.add(
            Project(
                id="sv_proj",
                name="带货项目",
                description="",
                style=ProjectStyle.real_people_city,
                visual_style=ProjectVisualStyle.live_action,
                seed=0,
                kind=ProjectKind.commerce_story.value,
                unify_style=True,
                progress=0,
                stats={},
            )
        )
        session.add(
            Chapter(
                id="sv_chap",
                project_id="sv_proj",
                index=1,
                title="第 1 章",
                summary="",
                raw_text="",
                condensed_text="",
                storyboard_count=0,
                status=ChapterStatus.draft,
            )
        )
        await session.commit()
        await bootstrap_builtin_story_formulas(session)
    return session_local, engine


def _make_override(session_local: async_sessionmaker[AsyncSession]):
    """与 ``get_db`` 同语义：成功 commit / 异常 rollback。"""

    async def _get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_local() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return _get_db


def _create_payload(formula_id: str = "underdog_triumph") -> dict[str, object]:
    """组装一个最小可用的 create body。"""
    return {
        "project_id": "sv_proj",
        "chapter_id": "sv_chap",
        "formula_id": formula_id,
        "script_full_text": "示例剧本内容...",
        "script_breakdown": {"beats": []},
        "archetype": None,
        "generated_by_task_id": None,
    }


@pytest.mark.asyncio
async def test_create_stores_draft_status_and_zero_score(client: TestClient) -> None:
    """create 强制 ``status=draft`` 与 ``compliance_score=0``。"""
    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.post("/api/v1/studio/story-variants", json=_create_payload())
        assert res.status_code == 201
        data = res.json()["data"]
        assert data["status"] == "draft"
        assert data["compliance_score"] == 0
        assert data["is_champion"] is False
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_requires_core_fields(client: TestClient) -> None:
    """create 缺必填字段应返回 422。"""
    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.post(
            "/api/v1/studio/story-variants",
            json={"project_id": "sv_proj"},
        )
        assert res.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_auto_generates_id(client: TestClient) -> None:
    """连续两次 create 得到不同的自动生成 id。"""
    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        first = client.post("/api/v1/studio/story-variants", json=_create_payload())
        second = client.post("/api/v1/studio/story-variants", json=_create_payload())
        assert first.status_code == 201
        assert second.status_code == 201
        a, b = first.json()["data"]["id"], second.json()["data"]["id"]
        assert a and b and a != b
        assert len(a) == 32
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_filtered_by_project_id(client: TestClient) -> None:
    """list 按 project_id 过滤命中（缺其它项目时全部命中）。"""
    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        client.post("/api/v1/studio/story-variants", json=_create_payload())
        client.post("/api/v1/studio/story-variants", json=_create_payload())
        res = client.get(
            "/api/v1/studio/story-variants",
            params={"project_id": "sv_proj"},
        )
        assert res.status_code == 200
        items = res.json()["data"]
        assert len(items) == 2
        assert {item["project_id"] for item in items} == {"sv_proj"}
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_ordered_by_created_at_desc(client: TestClient) -> None:
    """list 按 created_at desc 排序，最新创建的位于第 0 位。"""
    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        first = client.post("/api/v1/studio/story-variants", json=_create_payload()).json()["data"]
        # 第二条在数据库时间戳上严格晚于第一条；用单独 session 写入并指定毫秒级
        # 之后的 created_at 来避免 SQLite 同毫秒导致顺序模糊。
        from datetime import datetime, timedelta, timezone

        from app.models.story_formula import StoryVariant
        from app.models.types import StoryVariantStatus

        async with session_local() as session:
            session.add(
                StoryVariant(
                    id="forced_second",
                    project_id="sv_proj",
                    chapter_id="sv_chap",
                    formula_id="underdog_triumph",
                    script_full_text="x",
                    script_breakdown={},
                    status=StoryVariantStatus.draft.value,
                    is_champion=False,
                    compliance_score=0,
                )
            )
            await session.flush()
            obj = await session.get(StoryVariant, "forced_second")
            assert obj is not None
            obj.created_at = datetime.now(timezone.utc) + timedelta(seconds=10)
            await session.commit()

        res = client.get(
            "/api/v1/studio/story-variants",
            params={"project_id": "sv_proj"},
        )
        items = res.json()["data"]
        assert items[0]["id"] == "forced_second"
        assert items[1]["id"] == first["id"]
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_empty_returns_200(client: TestClient) -> None:
    """list 空集合返回 200 + 空数组。"""
    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get(
            "/api/v1/studio/story-variants",
            params={"project_id": "no_such_project"},
        )
        assert res.status_code == 200
        assert res.json()["data"] == []
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_422_on_blank_formula_id(client: TestClient) -> None:
    """formula_id 不允许空字符串（schema ``min_length=1``）。"""
    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        bad = _create_payload()
        bad["formula_id"] = ""
        res = client.post("/api/v1/studio/story-variants", json=bad)
        assert res.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_ignores_client_status_override(client: TestClient) -> None:
    """客户端伪造的 ``status=ready`` 字段会被丢弃，仍写入 draft。"""
    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        bad = _create_payload()
        bad["status"] = "ready"
        bad["is_champion"] = True
        bad["compliance_score"] = 99
        res = client.post("/api/v1/studio/story-variants", json=bad)
        assert res.status_code == 201
        data = res.json()["data"]
        assert data["status"] == "draft"
        assert data["is_champion"] is False
        assert data["compliance_score"] == 0
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()
