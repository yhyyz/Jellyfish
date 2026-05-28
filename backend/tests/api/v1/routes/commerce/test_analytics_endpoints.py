"""``/api/v1/commerce/analytics`` 归因聚合接口测试（W22-T3，P4 Wave B 2/11）。

覆盖 4 个维度（formula / hook / archetype / platform）× 多个 happy path
聚合断言 + 1 个枚举校验 + 1 个默认 metric 测试。
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
import app.models.brand_archetype  # noqa: F401  pylint: disable=unused-import
import app.models.commerce_assets  # noqa: F401  pylint: disable=unused-import
import app.models.compliance  # noqa: F401  pylint: disable=unused-import
import app.models.hook_pattern  # noqa: F401  pylint: disable=unused-import
import app.models.llm  # noqa: F401  pylint: disable=unused-import
import app.models.story_formula  # noqa: F401  pylint: disable=unused-import
import app.models.studio  # noqa: F401  pylint: disable=unused-import
import app.models.task  # noqa: F401  pylint: disable=unused-import
import app.models.task_links  # noqa: F401  pylint: disable=unused-import

from app.core.db import Base
from app.dependencies import get_db
from app.main import app
from app.models.brand_archetype import BrandArchetype
from app.models.hook_pattern import HookPattern
from app.models.story_formula import StoryFormula, StoryOutcome, StoryVariant
from app.models.studio import (
    Chapter,
    ChapterStatus,
    Project,
    ProjectStyle,
    ProjectVisualStyle,
)
from app.models.studio_prompts_files_timeline import PromptTemplate
from app.models.types import (
    FormulaRegion,
    Platform,
    ProjectKind,
    PromptCategory,
    StoryVariantStatus,
)


def _ts(hours_ago: int = 1) -> datetime:
    """返回过去 hours_ago 小时的 UTC 时间。"""
    return datetime.now(timezone.utc) - timedelta(hours=hours_ago)


async def _build_engine_with_fixtures() -> tuple[
    async_sessionmaker[AsyncSession], AsyncEngine
]:
    """构建 3 公式 × 3 outcome 矩阵的内存数据库。

    布局：
    - var_alpha: f_underdog / h_question / sage
        outcomes: douyin GMV=1000 c=0.6, tiktok GMV=2000 c=0.4
    - var_beta:  f_contrast / h_conflict / jester
        outcomes: douyin GMV=500 c=0.5
    - var_gamma: f_underdog / NULL hook / NULL archetype
        outcomes: kuaishou GMV=300 c=0.2
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_local() as session:
        session.add(
            PromptTemplate(
                id="t_stub",
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
                id="proj_x",
                name="带货",
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
                id="chap_x",
                project_id="proj_x",
                index=1,
                title="第 1 章",
                summary="",
                raw_text="",
                condensed_text="",
                storyboard_count=0,
                status=ChapterStatus.draft,
            )
        )
        session.add_all(
            [
                StoryFormula(
                    id="f_underdog",
                    name="凡人逆袭",
                    region=FormulaRegion.cn.value,
                    category="cn_viral",
                    structure={},
                    risk_flags=[],
                    typical_duration_sec=60,
                    typical_shot_count=4,
                    psychology="",
                    use_cases=[],
                    avoid_cases=[],
                    prompt_template_id="t_stub",
                    is_system=True,
                    sort_order=0,
                ),
                StoryFormula(
                    id="f_contrast",
                    name="对比反差",
                    region=FormulaRegion.cn.value,
                    category="cn_viral",
                    structure={},
                    risk_flags=[],
                    typical_duration_sec=45,
                    typical_shot_count=3,
                    psychology="",
                    use_cases=[],
                    avoid_cases=[],
                    prompt_template_id="t_stub",
                    is_system=True,
                    sort_order=1,
                ),
                HookPattern(
                    id="h_question",
                    name="问句钩子",
                    pattern_type="question",
                    description="",
                    template_text="",
                    psychology="",
                    use_cases=[],
                    avoid_cases=[],
                    is_system=True,
                    sort_order=0,
                ),
                HookPattern(
                    id="h_conflict",
                    name="冲突钩子",
                    pattern_type="conflict",
                    description="",
                    template_text="",
                    psychology="",
                    use_cases=[],
                    avoid_cases=[],
                    is_system=True,
                    sort_order=1,
                ),
                BrandArchetype(
                    id="sage",
                    name="Sage",
                    name_zh="智者",
                    motivation="",
                    voice_traits=[],
                    speech_patterns={},
                    sample_brands=[],
                    is_system=True,
                    sort_order=0,
                ),
                BrandArchetype(
                    id="jester",
                    name="Jester",
                    name_zh="小丑",
                    motivation="",
                    voice_traits=[],
                    speech_patterns={},
                    sample_brands=[],
                    is_system=True,
                    sort_order=1,
                ),
            ]
        )
        await session.commit()

        session.add_all(
            [
                StoryVariant(
                    id="var_alpha",
                    project_id="proj_x",
                    chapter_id="chap_x",
                    formula_id="f_underdog",
                    hook_pattern_id="h_question",
                    archetype="sage",
                    script_full_text="",
                    script_breakdown={},
                    status=StoryVariantStatus.draft.value,
                    is_champion=False,
                    compliance_score=0,
                ),
                StoryVariant(
                    id="var_beta",
                    project_id="proj_x",
                    chapter_id="chap_x",
                    formula_id="f_contrast",
                    hook_pattern_id="h_conflict",
                    archetype="jester",
                    script_full_text="",
                    script_breakdown={},
                    status=StoryVariantStatus.draft.value,
                    is_champion=False,
                    compliance_score=0,
                ),
                StoryVariant(
                    id="var_gamma",
                    project_id="proj_x",
                    chapter_id="chap_x",
                    formula_id="f_underdog",
                    hook_pattern_id=None,
                    archetype=None,
                    script_full_text="",
                    script_breakdown={},
                    status=StoryVariantStatus.draft.value,
                    is_champion=False,
                    compliance_score=0,
                ),
            ]
        )
        await session.commit()

        session.add_all(
            [
                StoryOutcome(
                    variant_id="var_alpha",
                    platform=Platform.douyin.value,
                    plays=10000,
                    completion_rate_3s=0.7,
                    completion_rate_full=0.6,
                    interactions=100,
                    cart_clicks=20,
                    orders=5,
                    gmv=1000.0,
                    notes="",
                    raw_payload={},
                    recorded_at=_ts(1),
                ),
                StoryOutcome(
                    variant_id="var_alpha",
                    platform=Platform.tiktok.value,
                    plays=20000,
                    completion_rate_3s=0.5,
                    completion_rate_full=0.4,
                    interactions=200,
                    cart_clicks=40,
                    orders=8,
                    gmv=2000.0,
                    notes="",
                    raw_payload={},
                    recorded_at=_ts(2),
                ),
                StoryOutcome(
                    variant_id="var_beta",
                    platform=Platform.douyin.value,
                    plays=5000,
                    completion_rate_3s=0.6,
                    completion_rate_full=0.5,
                    interactions=80,
                    cart_clicks=15,
                    orders=3,
                    gmv=500.0,
                    notes="",
                    raw_payload={},
                    recorded_at=_ts(3),
                ),
                StoryOutcome(
                    variant_id="var_gamma",
                    platform=Platform.kuaishou.value,
                    plays=3000,
                    completion_rate_3s=0.3,
                    completion_rate_full=0.2,
                    interactions=30,
                    cart_clicks=5,
                    orders=1,
                    gmv=300.0,
                    notes="",
                    raw_payload={},
                    recorded_at=_ts(4),
                ),
            ]
        )
        await session.commit()

    return session_local, engine


def _make_override(session_local: async_sessionmaker[AsyncSession]):
    """复刻 outcomes_crud 测试的 commit/rollback override。"""

    async def _get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_local() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return _get_db


@pytest.mark.asyncio
async def test_by_formula_sums_gmv_per_formula(client: TestClient) -> None:
    """按 formula 维度聚合 gmv：f_underdog=3300，f_contrast=500。"""
    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get("/api/v1/commerce/analytics/by-formula", params={"metric": "gmv"})
        assert res.status_code == 200, res.text
        body = res.json()["data"]
        assert body["dimension"] == "formula"
        assert body["metric"] == "gmv"

        points = {p["dimension_id"]: p for p in body["points"]}
        assert set(points) == {"f_underdog", "f_contrast"}
        assert points["f_underdog"]["metric_value"] == 3300.0
        assert points["f_underdog"]["dimension_name"] == "凡人逆袭"
        assert points["f_contrast"]["metric_value"] == 500.0
        assert points["f_contrast"]["dimension_name"] == "对比反差"

        ids = [p["dimension_id"] for p in body["points"]]
        assert ids.index("f_underdog") < ids.index("f_contrast")
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_by_hook_excludes_null_hooks(client: TestClient) -> None:
    """按 hook 聚合 gmv：仅 h_question (3000)、h_conflict (500) 进入。"""
    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get("/api/v1/commerce/analytics/by-hook", params={"metric": "gmv"})
        assert res.status_code == 200, res.text
        body = res.json()["data"]

        points = {p["dimension_id"]: p for p in body["points"]}
        assert set(points) == {"h_question", "h_conflict"}
        assert points["h_question"]["metric_value"] == 3000.0
        assert points["h_question"]["dimension_name"] == "问句钩子"
        assert points["h_conflict"]["metric_value"] == 500.0
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_by_archetype_avg_completion_rate(client: TestClient) -> None:
    """按 archetype 聚合 completion_rate_full（AVG）：sage=0.5，jester=0.5。"""
    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get(
            "/api/v1/commerce/analytics/by-archetype",
            params={"metric": "completion_rate_full"},
        )
        assert res.status_code == 200, res.text
        body = res.json()["data"]

        assert body["metric"] == "completion_rate_full"
        points = {p["dimension_id"]: p for p in body["points"]}
        assert set(points) == {"sage", "jester"}
        assert points["sage"]["metric_value"] == pytest.approx(0.5, rel=1e-6)
        assert points["sage"]["dimension_name"] == "智者"
        assert points["jester"]["metric_value"] == pytest.approx(0.5, rel=1e-6)
        assert points["jester"]["dimension_name"] == "小丑"
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_by_platform_sums_cart_clicks(client: TestClient) -> None:
    """按 platform 聚合 cart_clicks（SUM）：douyin=35, tiktok=40, kuaishou=5。"""
    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get(
            "/api/v1/commerce/analytics/by-platform",
            params={"metric": "cart_clicks"},
        )
        assert res.status_code == 200, res.text
        body = res.json()["data"]
        assert body["dimension"] == "platform"
        assert body["metric"] == "cart_clicks"

        points = {p["dimension_id"]: p for p in body["points"]}
        assert set(points) == {"douyin", "tiktok", "kuaishou"}
        assert points["douyin"]["metric_value"] == 35.0
        assert points["tiktok"]["metric_value"] == 40.0
        assert points["kuaishou"]["metric_value"] == 5.0
        assert points["douyin"]["dimension_name"] == "douyin"
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_metric_rejects_unknown_value(client: TestClient) -> None:
    """metric 走枚举校验，未知值 → 422。"""
    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get(
            "/api/v1/commerce/analytics/by-platform",
            params={"metric": "unsupported_metric"},
        )
        assert res.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_default_metric_is_gmv(client: TestClient) -> None:
    """缺省 metric 时默认走 gmv。"""
    session_local, engine = await _build_engine_with_fixtures()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        with_metric = client.get("/api/v1/commerce/analytics/by-platform", params={"metric": "gmv"})
        no_metric = client.get("/api/v1/commerce/analytics/by-platform")
        assert with_metric.status_code == 200
        assert no_metric.status_code == 200
        assert with_metric.json()["data"] == no_metric.json()["data"]
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()
