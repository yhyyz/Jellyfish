"""``/api/v1/studio/story-variants`` 接口测试（W6-T2 + W14-T3）。

测试范围（≥21 用例）：

W6-T2 基础接口（≥8）：

1. create 写入 ``status=draft`` + ``compliance_score=0`` 的变体。
2. create 必填校验：缺 project_id / chapter_id / formula_id 应返回 422。
3. create 自动生成 id（``uuid4().hex``，与请求体无关）。
4. list 按 ``project_id`` 过滤命中。
5. list 按 ``created_at desc`` 排序。
6. list 空集合返回 200 + 空数组。
7. create 422 on bad input（formula_id 为空字符串触发 ``min_length=1``）。
8. create 服务端忽略客户端伪造的 ``status=ready``（不可绕过 draft 默认）。

W14-T3 A/B 变体管理（≥13）：

9.  clone 生成新 id（与源变体不同）。
10. clone 默认深拷贝 ``script_breakdown``，与源变体内容相等但对象独立。
11. clone 仅覆盖 ``new_archetype`` 时只改 archetype。
12. clone 强制 ``status=draft``。
13. clone 强制 ``is_champion=False``。
14. clone 强制 ``compliance_score=0``。
15. clone 源变体不存在 → 404。
16. clone 拒绝额外未声明字段（``extra="forbid"`` → 422）。
17. mark_champion 把目标变体 ``is_champion`` 置为 True。
18. mark_champion 同章节其它变体的 ``is_champion`` 被清空。
19. mark_champion 不影响其它章节 / 其它项目下的冠军。
20. mark_champion 幂等（重复调用得到同一结果）。
21. mark_champion 目标变体不存在 → 404。
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


# ---------------------------------------------------------------------------
# W14-T3：变体克隆 + 冠军标记
# ---------------------------------------------------------------------------


async def _create_source_variant(client: TestClient, **overrides: object) -> dict[str, object]:
    """创建一个供后续克隆/冠军测试复用的源变体并返回响应 data。"""
    payload = _create_payload()
    payload.update(overrides)
    res = client.post("/api/v1/studio/story-variants", json=payload)
    assert res.status_code == 201, res.text
    return res.json()["data"]


@pytest.mark.asyncio
async def test_clone_variant_creates_new_id(client: TestClient) -> None:
    """克隆得到的新变体 id 与源变体不同，且为 32 位 hex。"""
    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        source = await _create_source_variant(client)
        res = client.post(f"/api/v1/studio/story-variants/{source['id']}/clone", json={})
        assert res.status_code == 201, res.text
        data = res.json()["data"]
        assert data["id"] != source["id"]
        assert len(data["id"]) == 32
        assert data["project_id"] == source["project_id"]
        assert data["chapter_id"] == source["chapter_id"]
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_clone_variant_preserves_script_breakdown_by_default(client: TestClient) -> None:
    """未传覆盖字段时，剧本与镜头分解从源变体深拷贝（值等价、对象独立）。"""
    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        payload = _create_payload()
        payload["script_breakdown"] = {"beats": [{"id": "b1", "text": "开场"}]}
        payload["script_full_text"] = "完整剧本 demo"
        res = client.post("/api/v1/studio/story-variants", json=payload)
        source = res.json()["data"]

        clone_res = client.post(
            f"/api/v1/studio/story-variants/{source['id']}/clone",
            json={},
        )
        assert clone_res.status_code == 201
        cloned = clone_res.json()["data"]
        assert cloned["script_full_text"] == source["script_full_text"]
        assert cloned["script_breakdown"] == source["script_breakdown"]
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_clone_variant_with_archetype_override_updates_only_archetype(
    client: TestClient,
) -> None:
    """仅传 ``new_archetype`` 时只覆盖 archetype，其它继承源变体。"""
    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        source = await _create_source_variant(client, archetype="hero")
        res = client.post(
            f"/api/v1/studio/story-variants/{source['id']}/clone",
            json={"new_archetype": "outlaw"},
        )
        assert res.status_code == 201
        data = res.json()["data"]
        assert data["archetype"] == "outlaw"
        assert data["formula_id"] == source["formula_id"]
        assert data["hook_pattern_id"] == source["hook_pattern_id"]
        assert data["cta_pattern_id"] == source["cta_pattern_id"]
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_clone_variant_resets_status_to_draft(client: TestClient) -> None:
    """即便源变体 status=ready，克隆出来的新变体也强制 draft。"""
    from app.models.story_formula import StoryVariant
    from app.models.types import StoryVariantStatus

    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        source = await _create_source_variant(client)
        async with session_local() as session:
            obj = await session.get(StoryVariant, source["id"])
            assert obj is not None
            obj.status = StoryVariantStatus.ready
            await session.commit()

        res = client.post(f"/api/v1/studio/story-variants/{source['id']}/clone", json={})
        assert res.status_code == 201
        assert res.json()["data"]["status"] == "draft"
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_clone_variant_resets_is_champion_to_false(client: TestClient) -> None:
    """源变体 is_champion=True 时，克隆出来的新变体仍然是 False。"""
    from app.models.story_formula import StoryVariant

    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        source = await _create_source_variant(client)
        async with session_local() as session:
            obj = await session.get(StoryVariant, source["id"])
            assert obj is not None
            obj.is_champion = True
            await session.commit()

        res = client.post(f"/api/v1/studio/story-variants/{source['id']}/clone", json={})
        assert res.status_code == 201
        assert res.json()["data"]["is_champion"] is False
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_clone_variant_resets_compliance_score_to_zero(client: TestClient) -> None:
    """源变体已有合规评分时，克隆出来的新变体重置为 0。"""
    from app.models.story_formula import StoryVariant

    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        source = await _create_source_variant(client)
        async with session_local() as session:
            obj = await session.get(StoryVariant, source["id"])
            assert obj is not None
            obj.compliance_score = 88
            await session.commit()

        res = client.post(f"/api/v1/studio/story-variants/{source['id']}/clone", json={})
        assert res.status_code == 201
        assert res.json()["data"]["compliance_score"] == 0
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_clone_variant_404_on_missing_source(client: TestClient) -> None:
    """克隆不存在的源变体 → 404 + entity_not_found 文案。"""
    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.post(
            "/api/v1/studio/story-variants/no_such_variant/clone",
            json={},
        )
        assert res.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_clone_variant_validates_extra_fields(client: TestClient) -> None:
    """``extra="forbid"`` 拒绝未声明字段，例如 ``status`` / ``is_champion``。"""
    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        source = await _create_source_variant(client)
        res = client.post(
            f"/api/v1/studio/story-variants/{source['id']}/clone",
            json={"status": "ready"},
        )
        assert res.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_mark_champion_sets_is_champion_true(client: TestClient) -> None:
    """PATCH /champion 使目标变体 is_champion=True。"""
    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        source = await _create_source_variant(client)
        assert source["is_champion"] is False
        res = client.patch(f"/api/v1/studio/story-variants/{source['id']}/champion")
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert data["id"] == source["id"]
        assert data["is_champion"] is True
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_mark_champion_unsets_other_champions_in_same_chapter(client: TestClient) -> None:
    """同 (project, chapter) 下其它变体的 is_champion 在标记新冠军时被清空。"""
    from app.models.story_formula import StoryVariant

    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        first = await _create_source_variant(client)
        second = await _create_source_variant(client)
        async with session_local() as session:
            obj = await session.get(StoryVariant, first["id"])
            assert obj is not None
            obj.is_champion = True
            await session.commit()

        res = client.patch(f"/api/v1/studio/story-variants/{second['id']}/champion")
        assert res.status_code == 200
        assert res.json()["data"]["is_champion"] is True

        async with session_local() as session:
            previous = await session.get(StoryVariant, first["id"])
            assert previous is not None
            assert previous.is_champion is False
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_mark_champion_does_not_affect_other_chapters_or_projects(
    client: TestClient,
) -> None:
    """其它章节 / 其它项目的冠军不受影响。"""
    from app.models.story_formula import StoryVariant
    from app.models.studio import (
        Chapter,
        ChapterStatus,
        Project,
        ProjectStyle,
        ProjectVisualStyle,
    )
    from app.models.types import ProjectKind, StoryVariantStatus

    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        async with session_local() as session:
            session.add(
                Chapter(
                    id="sv_chap_other",
                    project_id="sv_proj",
                    index=2,
                    title="第 2 章",
                    summary="",
                    raw_text="",
                    condensed_text="",
                    storyboard_count=0,
                    status=ChapterStatus.draft,
                )
            )
            session.add(
                Project(
                    id="sv_proj_other",
                    name="另一个项目",
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
                    id="sv_chap_in_other_proj",
                    project_id="sv_proj_other",
                    index=1,
                    title="他项目第 1 章",
                    summary="",
                    raw_text="",
                    condensed_text="",
                    storyboard_count=0,
                    status=ChapterStatus.draft,
                )
            )
            session.add(
                StoryVariant(
                    id="champ_other_chapter",
                    project_id="sv_proj",
                    chapter_id="sv_chap_other",
                    formula_id="underdog_triumph",
                    script_full_text="",
                    script_breakdown={},
                    status=StoryVariantStatus.draft.value,
                    is_champion=True,
                    compliance_score=0,
                )
            )
            session.add(
                StoryVariant(
                    id="champ_other_project",
                    project_id="sv_proj_other",
                    chapter_id="sv_chap_in_other_proj",
                    formula_id="underdog_triumph",
                    script_full_text="",
                    script_breakdown={},
                    status=StoryVariantStatus.draft.value,
                    is_champion=True,
                    compliance_score=0,
                )
            )
            await session.commit()

        target = await _create_source_variant(client)
        res = client.patch(f"/api/v1/studio/story-variants/{target['id']}/champion")
        assert res.status_code == 200

        async with session_local() as session:
            other_chapter = await session.get(StoryVariant, "champ_other_chapter")
            other_project = await session.get(StoryVariant, "champ_other_project")
            assert other_chapter is not None and other_chapter.is_champion is True
            assert other_project is not None and other_project.is_champion is True
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_mark_champion_idempotent(client: TestClient) -> None:
    """同一变体重复 PATCH /champion 仍返回 is_champion=True。"""
    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        source = await _create_source_variant(client)
        first = client.patch(f"/api/v1/studio/story-variants/{source['id']}/champion")
        second = client.patch(f"/api/v1/studio/story-variants/{source['id']}/champion")
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["data"]["is_champion"] is True
        assert second.json()["data"]["is_champion"] is True
        assert first.json()["data"]["id"] == second.json()["data"]["id"] == source["id"]
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_mark_champion_404_on_missing_variant(client: TestClient) -> None:
    """目标变体不存在 → 404。"""
    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.patch("/api/v1/studio/story-variants/no_such_variant/champion")
        assert res.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()
