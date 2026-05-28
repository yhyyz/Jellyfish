"""W30-T2 subtitle_style_service.resolve_for_shot 单元测试。

覆盖 3 个核心场景：

1. system only：项目无任何覆盖样式 → resolve_for_shot 返回系统级行。
2. project override exists：项目级同名覆盖存在 → 返回项目级行（不
   退化为系统级）。
3. project override deleted：项目级覆盖被删后再 resolve → 自动
   fallback 到系统级。

辅助场景：

4. style_id_hint 直接命中本项目级行 → 短路返回 hint 本身。
5. shot 不存在 → 抛 LookupError。
6. 系统级 seed 行不存在（没有 douyin_default）→ 抛 LookupError。
"""

# pylint: disable=redefined-outer-name,too-few-public-methods

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# 必须 import 全部模型以确保 Base.metadata 拥有完整 schema。
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
from app.models.studio_projects import Chapter, Project
from app.models.studio_shots import Shot
from app.models.subtitle import SubtitleStyle
from app.models.types import (
    AudioStrategy,
    ProductFocusLevel,
    ShotStatus,
    SubtitleAlignment,
    SubtitleFormat,
)
from app.services.studio.subtitle_style_service import (
    SYSTEM_DEFAULT_STYLE_ID,
    resolve_for_shot,
)


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    """构造 file-backed SQLite 引擎；与其它 studio worker 测试同样的模板。"""
    db_path = tmp_path / "subtitle-style-service.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_local = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield session_local
    await engine.dispose()


def _build_system_style(
    *,
    style_id: str = SYSTEM_DEFAULT_STYLE_ID,
    name: str = "抖音默认",
) -> SubtitleStyle:
    """构造一条 W18 系统级 seed 行（``project_id=None``）。"""
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


def _build_project_style(
    *,
    style_id: str,
    name: str,
    project_id: str,
    font_size: int = 72,
) -> SubtitleStyle:
    """构造一条项目级覆盖行（``project_id`` 非空，``is_system=False``）。"""
    return SubtitleStyle(
        id=style_id,
        name=name,
        description="",
        language_code="zh-CN",
        format=SubtitleFormat.ass,
        font_family="Source Han Sans CN Heavy",
        font_fallback_chain=[],
        font_size=font_size,
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
        is_system=False,
        sort_order=0,
        project_id=project_id,
    )


async def _seed_project_chapter_shot(
    session: AsyncSession,
    *,
    project_id: str = "proj-1",
    chapter_id: str = "chap-1",
    shot_id: str = "shot-1",
) -> None:
    """在 session 内建一条最小可用的 ``Project → Chapter → Shot`` 链。"""
    project = Project(
        id=project_id,
        name="Demo Project",
        description="",
        style="modern",
    )
    chapter = Chapter(
        id=chapter_id,
        project_id=project_id,
        title="Chapter 1",
        index=1,
    )
    shot = Shot(
        id=shot_id,
        chapter_id=chapter_id,
        index=1,
        title="Shot 1",
        status=ShotStatus.ready,
        audio_strategy=AudioStrategy.silent_with_tts,
        product_focus_level=ProductFocusLevel.none,
    )
    session.add_all([project, chapter, shot])
    await session.flush()


# ---------------------------------------------------------------------------
# scenario 1: system only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_falls_back_to_system_when_no_project_override(
    session_factory,
) -> None:
    """系统级 seed 存在 + 无项目覆盖 → resolve 返回系统级行。"""
    async with session_factory() as session:
        await _seed_project_chapter_shot(session)
        session.add(_build_system_style())
        await session.commit()

        style = await resolve_for_shot(
            session,
            shot_id="shot-1",
            style_id_hint=SYSTEM_DEFAULT_STYLE_ID,
        )
        assert style.id == SYSTEM_DEFAULT_STYLE_ID
        assert style.project_id is None
        assert style.is_system is True


# ---------------------------------------------------------------------------
# scenario 2: project override exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_prefers_project_override_when_same_name_exists(
    session_factory,
) -> None:
    """项目级同名覆盖存在 → resolve 返回项目级行（不退化为系统级）。"""
    async with session_factory() as session:
        await _seed_project_chapter_shot(session)
        session.add(_build_system_style())
        session.add(
            _build_project_style(
                style_id="proj1_douyin",
                name="抖音默认",
                project_id="proj-1",
                font_size=80,
            )
        )
        await session.commit()

        style = await resolve_for_shot(
            session,
            shot_id="shot-1",
            style_id_hint=SYSTEM_DEFAULT_STYLE_ID,
        )
        assert style.id == "proj1_douyin"
        assert style.project_id == "proj-1"
        assert style.is_system is False
        assert style.font_size == 80


# ---------------------------------------------------------------------------
# scenario 3: project override deleted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_falls_back_when_project_override_deleted(
    session_factory,
) -> None:
    """项目级覆盖被删后再 resolve → 自动 fallback 到系统级。"""
    async with session_factory() as session:
        await _seed_project_chapter_shot(session)
        session.add(_build_system_style())
        override = _build_project_style(
            style_id="proj1_douyin",
            name="抖音默认",
            project_id="proj-1",
        )
        session.add(override)
        await session.commit()

        style_first = await resolve_for_shot(
            session,
            shot_id="shot-1",
            style_id_hint=SYSTEM_DEFAULT_STYLE_ID,
        )
        assert style_first.id == "proj1_douyin"

        await session.delete(override)
        await session.commit()

        style_after = await resolve_for_shot(
            session,
            shot_id="shot-1",
            style_id_hint=SYSTEM_DEFAULT_STYLE_ID,
        )
        assert style_after.id == SYSTEM_DEFAULT_STYLE_ID
        assert style_after.project_id is None


# ---------------------------------------------------------------------------
# scenario 4: hint 直接命中
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_short_circuits_when_hint_matches_project(
    session_factory,
) -> None:
    """style_id_hint 已属于当前 project → 短路返回 hint 本身。"""
    async with session_factory() as session:
        await _seed_project_chapter_shot(session)
        session.add(_build_system_style())
        session.add(
            _build_project_style(
                style_id="proj1_custom",
                name="项目自定义大字幕",
                project_id="proj-1",
            )
        )
        await session.commit()

        style = await resolve_for_shot(
            session,
            shot_id="shot-1",
            style_id_hint="proj1_custom",
        )
        assert style.id == "proj1_custom"


# ---------------------------------------------------------------------------
# scenario 5: shot 不存在
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_raises_when_shot_missing(session_factory) -> None:
    """shot_id 在 DB 中不存在时必须抛 LookupError。"""
    async with session_factory() as session:
        session.add(_build_system_style())
        await session.commit()

        with pytest.raises(LookupError) as exc_info:
            await resolve_for_shot(
                session,
                shot_id="not-exist",
                style_id_hint=None,
            )
        assert "Shot not found" in str(exc_info.value)


# ---------------------------------------------------------------------------
# scenario 6: 系统级 seed 缺失
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_raises_when_no_style_resolvable(session_factory) -> None:
    """既无项目级也无系统级行时必须抛 LookupError。"""
    async with session_factory() as session:
        await _seed_project_chapter_shot(session)
        await session.commit()

        with pytest.raises(LookupError) as exc_info:
            await resolve_for_shot(
                session,
                shot_id="shot-1",
                style_id_hint=None,
            )
        assert "not resolvable" in str(exc_info.value)
