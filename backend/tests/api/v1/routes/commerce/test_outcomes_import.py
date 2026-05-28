"""``/api/v1/commerce/outcomes/import`` 路由测试（W22-T2，P4 Wave B 1/11）。

TDD 覆盖（≥ 3）：

1. ``test_route_returns_summary_with_inserted_failed_counts``：抖音
   sample CSV 上传 → 200 + ``inserted=3 / failed=0``。
2. ``test_route_handles_malformed_rows_without_aborting``：包含非法行的
   CSV 上传 → 200 + ``failed > 0``，``inserted > 0``，``errors`` 列表
   带 ``row_index`` / ``raw_row`` / ``reason``。
3. ``test_route_rejects_oversized_file_with_413``：``Content-Length`` 超
   过 5MB 时直接返回 413，不会进入 service 层。
"""

# pylint: disable=invalid-name

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


_FIXTURES_DIR = Path(__file__).resolve().parents[4] / "_fixtures"


async def _build_engine() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
    """构建一次性 SQLite + Project + Chapter + var_alpha 变体。"""
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
        session.add(
            StoryVariant(
                id="var_alpha",
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
    return session_local, engine


def _make_override(session_local: async_sessionmaker[AsyncSession]):
    """与 outcomes CRUD 测试一致的 commit/rollback 语义。"""

    async def _get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_local() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return _get_db


def _fixture_bytes(name: str) -> bytes:
    """读取 fixture 并把 ``2025-12-2X`` 替换成"今天-1"，避免未来时间断言失败。"""
    raw = (_FIXTURES_DIR / name).read_bytes()
    text = raw.decode("utf-8")
    if "2025-12-" in text:
        today = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        for tail in ("21", "22", "23", "24", "25", "26"):
            text = text.replace(f"2025-12-{tail}", today)
    return text.encode("utf-8")


@pytest.mark.asyncio
async def test_route_returns_summary_with_inserted_failed_counts(client: TestClient) -> None:
    """抖音 sample CSV 上传 → 200，summary 字段齐全。"""
    session_local, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        body = _fixture_bytes("outcomes_douyin_sample.csv")
        res = client.post(
            "/api/v1/commerce/outcomes/import",
            files={"file": ("douyin.csv", body, "text/csv")},
            data={"mapping_profile": "douyin"},
        )
        assert res.status_code == 200, res.text
        summary = res.json()["data"]
        assert summary["mapping_profile"] == "douyin"
        assert summary["total_rows"] == 3
        assert summary["inserted"] == 3
        assert summary["failed"] == 0
        assert summary["errors"] == []
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_route_handles_malformed_rows_without_aborting(client: TestClient) -> None:
    """非法行 → 200 + failed>0；errors 列表包含 row_index / raw_row / reason。"""
    session_local, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        body = _fixture_bytes("outcomes_malformed.csv")
        res = client.post(
            "/api/v1/commerce/outcomes/import",
            files={"file": ("bad.csv", body, "text/csv")},
            data={"mapping_profile": "douyin"},
        )
        assert res.status_code == 200, res.text
        summary = res.json()["data"]
        assert summary["total_rows"] == 6
        assert summary["inserted"] == 2
        assert summary["failed"] == 4
        for err in summary["errors"]:
            assert err["row_index"] >= 2
            assert isinstance(err["raw_row"], dict)
            assert err["reason"]
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_route_rejects_oversized_file_with_413(client: TestClient) -> None:
    """``Content-Length`` > 5MB → 413，不进入 service。"""
    session_local, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        # 不真的发 6MB 字节流（CI 时间太长），用伪造 header 触发前置检查。
        # TestClient 不允许直接覆盖 multipart 的 Content-Length，因此构造
        # 一个超大 payload；用 6MB 的占位字节即可命中前置 413。
        oversized_body = b"x" * (6 * 1024 * 1024)
        res = client.post(
            "/api/v1/commerce/outcomes/import",
            files={"file": ("big.csv", oversized_body, "text/csv")},
            data={"mapping_profile": "default"},
        )
        assert res.status_code == 413, res.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_route_xhs_profile_translates_percent_completion_rate(
    client: TestClient,
) -> None:
    """小红书 profile 经路由层正常解析 "85%" → 0.85，无错误行。"""
    session_local, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        body = _fixture_bytes("outcomes_xhs_sample.csv")
        res = client.post(
            "/api/v1/commerce/outcomes/import",
            files={"file": ("xhs.csv", body, "text/csv")},
            data={"mapping_profile": "xiaohongshu"},
        )
        assert res.status_code == 200, res.text
        summary = res.json()["data"]
        assert summary["mapping_profile"] == "xiaohongshu"
        assert summary["inserted"] == 2
        assert summary["failed"] == 0
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_route_rejects_non_csv_extension_with_400(client: TestClient) -> None:
    """非 .csv 后缀 → 400，避免 Excel xlsx 被误传上来导致解析爆栈。"""
    session_local, engine = await _build_engine()
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.post(
            "/api/v1/commerce/outcomes/import",
            files={"file": ("data.xlsx", b"PK\x03\x04", "application/octet-stream")},
            data={"mapping_profile": "default"},
        )
        assert res.status_code == 400, res.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()
