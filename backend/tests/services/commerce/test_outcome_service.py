"""StoryOutcome service 层单元测试（W22-T1，P4 Wave A 1/6）。

聚焦校验规则与 service-层 CRUD：

1. ``test_create_validates_completion_rate_range``：``completion_rate_3s``
   或 ``completion_rate_full`` 不在 ``[0, 1]`` 时抛 ``HTTPException 400``。
2. ``test_create_validates_gmv_non_negative``：``gmv < 0`` 时抛
   ``HTTPException 400``。
3. ``test_create_validates_recorded_at_not_future``：``recorded_at`` 不允许
   超过当前时间，否则抛 ``HTTPException 400``。
4. ``test_update_returns_404_when_missing``：PATCH 不存在的记录 → 404。
"""

# pylint: disable=invalid-name

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
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
from app.models.story_formula import StoryVariant
from app.models.studio import Chapter, ChapterStatus, Project, ProjectStyle, ProjectVisualStyle
from app.models.studio_prompts_files_timeline import PromptTemplate
from app.models.types import Platform, ProjectKind, PromptCategory, StoryVariantStatus
from app.schemas.commerce.outcome import StoryOutcomeCreate, StoryOutcomeUpdate
from app.services.commerce.builtin_story_formulas import (
    BUILTIN_FORMULA_PROMPT_TEMPLATE_ID,
    bootstrap_builtin_story_formulas,
)
from app.services.commerce.outcome_service import StoryOutcomeService


async def _build_session() -> AsyncGenerator[AsyncSession, None]:
    """构建内存 SQLite session 并写入最小 fixtures（Project + Chapter + 1 variant）。"""
    engine: AsyncEngine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
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
        yield session
    await engine.dispose()


def _ok_create(**overrides: object) -> StoryOutcomeCreate:
    """组装一个合法 StoryOutcomeCreate；overrides 用于构造非法字段触发校验失败。"""
    base: dict[str, object] = {
        "variant_id": "var_alpha",
        "platform": Platform.douyin,
        "plays": 100,
        "completion_rate_3s": 0.5,
        "completion_rate_full": 0.3,
        "interactions": 10,
        "cart_clicks": 2,
        "orders": 1,
        "gmv": 100.0,
        "notes": "",
        "raw_payload": {},
        "recorded_at": datetime.now(timezone.utc) - timedelta(hours=1),
    }
    base.update(overrides)
    return StoryOutcomeCreate.model_validate(base)


@pytest.mark.asyncio
async def test_create_validates_completion_rate_range() -> None:
    """``completion_rate_3s > 1`` 或 ``< 0`` → 抛 400 HTTPException。

    pydantic schema 同样会拒绝越界值；service 层在校验时直接复用 schema
    的边界（兜底），即便 schema 被绕过，service 层也会主动抛异常。
    """
    async for db in _build_session():
        svc = StoryOutcomeService(db)

        # schema 层兜底
        with pytest.raises(Exception):
            _ok_create(completion_rate_3s=1.2)
        with pytest.raises(Exception):
            _ok_create(completion_rate_full=-0.5)

        # 模型构造合法但人为破坏：直接调 service 业务校验函数路径
        # 通过反射构造一个绕过 schema 的 payload 验证 service 自己的二次校验。
        bad = _ok_create()
        bad.completion_rate_3s = 1.2  # type: ignore[misc]
        with pytest.raises(HTTPException) as exc:
            await svc.create(bad)
        assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_validates_gmv_non_negative() -> None:
    """``gmv < 0`` 时 service 层抛 HTTPException 400。"""
    async for db in _build_session():
        svc = StoryOutcomeService(db)

        # schema 兜底
        with pytest.raises(Exception):
            _ok_create(gmv=-0.01)

        # service 二次校验：构造合法 schema 后篡改字段。
        bad = _ok_create()
        bad.gmv = -10.0  # type: ignore[misc]
        with pytest.raises(HTTPException) as exc:
            await svc.create(bad)
        assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_validates_recorded_at_not_future() -> None:
    """``recorded_at`` 落在未来时 service 层拒绝。"""
    async for db in _build_session():
        svc = StoryOutcomeService(db)
        future_payload = _ok_create()
        future_payload.recorded_at = datetime.now(timezone.utc) + timedelta(days=1)  # type: ignore[misc]
        with pytest.raises(HTTPException) as exc:
            await svc.create(future_payload)
        assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_update_returns_404_when_missing() -> None:
    """PATCH 不存在的记录 → 404 HTTPException。"""
    async for db in _build_session():
        svc = StoryOutcomeService(db)
        with pytest.raises(HTTPException) as exc:
            await svc.update(999999, StoryOutcomeUpdate())
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_then_list_then_delete_round_trip() -> None:
    """端到端：create → list 命中 → delete → list 为空。"""
    async for db in _build_session():
        svc = StoryOutcomeService(db)
        created = await svc.create(_ok_create())
        listed = await svc.list_by_variant("var_alpha")
        assert len(listed) == 1
        assert listed[0].id == created.id

        await svc.delete(created.id)
        listed_after = await svc.list_by_variant("var_alpha")
        assert listed_after == []
