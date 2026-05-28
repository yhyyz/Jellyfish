"""``/api/v1/commerce/outcomes`` 接口测试（W22-T1，P4 Wave A 1/6）。

P4 阶段激活 P1 已建好的 ``story_outcomes`` 表（参见
``backend/app/models/story_formula.py:309``），承担"投放效果手动录入"的最小
CRUD 入口。本测试集覆盖 6 类用例：

1. ``test_create_outcome_returns_201``：合法 payload 创建成功，回填 id /
   recorded_at / 默认值（plays / interactions / cart_clicks / orders / gmv）。
2. ``test_create_outcome_rejects_negative_gmv_400``：``gmv`` 必须 ≥ 0，
   服务端返回 400 + entity 错误文案。
3. ``test_create_outcome_rejects_completion_rate_out_of_range``：
   ``completion_rate_3s`` / ``completion_rate_full`` 必须在 ``[0, 1]`` 区间。
4. ``test_list_outcomes_filters_by_variant_id``：列表接口按 ``variant_id``
   过滤；其它变体的记录不会泄漏。
5. ``test_patch_outcome_partial_update``：部分字段更新（仅修改 ``gmv``）不
   覆盖其它字段，保留原值。
6. ``test_delete_outcome``：删除后再次 GET 列表为空。
"""

# pylint: disable=invalid-name

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone

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
from app.models.story_formula import StoryVariant
from app.models.studio import Chapter, ChapterStatus, Project, ProjectStyle, ProjectVisualStyle
from app.models.studio_prompts_files_timeline import PromptTemplate
from app.models.types import ProjectKind, PromptCategory, StoryVariantStatus
from app.services.commerce.builtin_story_formulas import (
    BUILTIN_FORMULA_PROMPT_TEMPLATE_ID,
    bootstrap_builtin_story_formulas,
)


# ---------------------------------------------------------------------------
# 测试夹具：内存 SQLite + Project + Chapter + 2 个 StoryVariant
# ---------------------------------------------------------------------------


async def _build_engine_with_fixtures() -> tuple[
    async_sessionmaker[AsyncSession], AsyncEngine, dict[str, str]
]:
    """构建一次性 SQLite 引擎并写入 Project + Chapter + 2 个 StoryVariant。

    返回的 ``ids`` 字典包含两个 variant_id，便于 list 过滤用例验证"互不干扰"。
    """
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
                id="oc_proj",
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
                id="oc_chap",
                project_id="oc_proj",
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

        # 两个 variant：用于过滤验证。
        for vid in ("var_alpha", "var_beta"):
            session.add(
                StoryVariant(
                    id=vid,
                    project_id="oc_proj",
                    chapter_id="oc_chap",
                    formula_id="underdog_triumph",
                    script_full_text="",
                    script_breakdown={},
                    status=StoryVariantStatus.draft.value,
                    is_champion=False,
                    compliance_score=0,
                )
            )
        await session.commit()

    return session_local, engine, {"variant_a": "var_alpha", "variant_b": "var_beta"}


def _make_override(session_local: async_sessionmaker[AsyncSession]):
    """复用 ``get_db`` 的 commit/rollback 语义，确保 PATCH/DELETE 真正落库。"""

    async def _get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_local() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return _get_db


def _payload(variant_id: str, **overrides: object) -> dict[str, object]:
    """组装一个最小可用的 POST body。

    ``recorded_at`` 取 ``now - 1 小时`` 落到合法窗口；caller 可传入覆盖。
    """
    base: dict[str, object] = {
        "variant_id": variant_id,
        "platform": "douyin",
        "plays": 12345,
        "completion_rate_3s": 0.55,
        "completion_rate_full": 0.32,
        "interactions": 200,
        "cart_clicks": 30,
        "orders": 10,
        "gmv": 1280.5,
        "notes": "首日数据",
        "raw_payload": {"raw": "x"},
        "recorded_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_outcome_returns_201(client: TestClient) -> None:
    """合法 payload → 201；返回 id 与回填的所有字段。"""
    session_local, engine, ids = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        body = _payload(ids["variant_a"])
        res = client.post("/api/v1/commerce/outcomes", json=body)
        assert res.status_code == 201, res.text
        data = res.json()["data"]
        assert isinstance(data["id"], int) and data["id"] > 0
        assert data["variant_id"] == ids["variant_a"]
        assert data["platform"] == "douyin"
        assert data["gmv"] == 1280.5
        assert data["plays"] == 12345
        assert data["completion_rate_3s"] == 0.55
        assert data["completion_rate_full"] == 0.32
        assert data["notes"] == "首日数据"
        assert data["raw_payload"] == {"raw": "x"}
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_outcome_rejects_negative_gmv_400(client: TestClient) -> None:
    """``gmv < 0`` → 400（业务规则，由 service 层强制）。"""
    session_local, engine, ids = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        body = _payload(ids["variant_a"], gmv=-1.0)
        res = client.post("/api/v1/commerce/outcomes", json=body)
        # pydantic 也可以在 schema 层做 ge=0；任一 4xx 都视为契约满足。
        assert res.status_code in (400, 422), res.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_outcome_rejects_completion_rate_out_of_range(client: TestClient) -> None:
    """``completion_rate_3s`` / ``completion_rate_full`` 必须 ∈ [0, 1]。"""
    session_local, engine, ids = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        body = _payload(ids["variant_a"], completion_rate_3s=1.5)
        res = client.post("/api/v1/commerce/outcomes", json=body)
        assert res.status_code in (400, 422), res.text

        body2 = _payload(ids["variant_a"], completion_rate_full=-0.1)
        res2 = client.post("/api/v1/commerce/outcomes", json=body2)
        assert res2.status_code in (400, 422), res2.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_outcome_rejects_future_recorded_at(client: TestClient) -> None:
    """``recorded_at > now`` 不允许，由 service 层校验返回 400/422。"""
    session_local, engine, ids = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        body = _payload(ids["variant_a"], recorded_at=future)
        res = client.post("/api/v1/commerce/outcomes", json=body)
        assert res.status_code in (400, 422), res.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_outcomes_filters_by_variant_id(client: TestClient) -> None:
    """``GET .../variants/{variant_id}/outcomes`` 只返回该变体的记录。"""
    session_local, engine, ids = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        for _ in range(2):
            client.post("/api/v1/commerce/outcomes", json=_payload(ids["variant_a"]))
        client.post("/api/v1/commerce/outcomes", json=_payload(ids["variant_b"]))

        res_a = client.get(f"/api/v1/commerce/variants/{ids['variant_a']}/outcomes")
        assert res_a.status_code == 200
        items_a = res_a.json()["data"]
        assert len(items_a) == 2
        assert {it["variant_id"] for it in items_a} == {ids["variant_a"]}

        res_b = client.get(f"/api/v1/commerce/variants/{ids['variant_b']}/outcomes")
        assert res_b.status_code == 200
        items_b = res_b.json()["data"]
        assert len(items_b) == 1
        assert items_b[0]["variant_id"] == ids["variant_b"]
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_patch_outcome_partial_update(client: TestClient) -> None:
    """PATCH 仅更新显式提供的字段，其它字段保留原值。"""
    session_local, engine, ids = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        create = client.post("/api/v1/commerce/outcomes", json=_payload(ids["variant_a"]))
        assert create.status_code == 201, create.text
        outcome_id = create.json()["data"]["id"]

        res = client.patch(
            f"/api/v1/commerce/outcomes/{outcome_id}",
            json={"gmv": 9999.0, "notes": "复盘后调整"},
        )
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert data["gmv"] == 9999.0
        assert data["notes"] == "复盘后调整"
        # 未传字段保持原值
        assert data["plays"] == 12345
        assert data["completion_rate_3s"] == 0.55
        assert data["raw_payload"] == {"raw": "x"}
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_delete_outcome(client: TestClient) -> None:
    """DELETE 后再次 GET 列表不再包含该记录。"""
    session_local, engine, ids = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        create = client.post("/api/v1/commerce/outcomes", json=_payload(ids["variant_a"]))
        outcome_id = create.json()["data"]["id"]

        res = client.delete(f"/api/v1/commerce/outcomes/{outcome_id}")
        assert res.status_code in (200, 204), res.text

        # 查询列表应为空
        list_res = client.get(f"/api/v1/commerce/variants/{ids['variant_a']}/outcomes")
        assert list_res.status_code == 200
        assert list_res.json()["data"] == []
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_patch_unknown_outcome_returns_404(client: TestClient) -> None:
    """PATCH 不存在的 outcome → 404。"""
    session_local, engine, _ids = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.patch("/api/v1/commerce/outcomes/99999", json={"gmv": 1.0})
        assert res.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()
