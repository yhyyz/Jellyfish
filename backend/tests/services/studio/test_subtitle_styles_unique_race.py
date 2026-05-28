"""W30-followup: subtitle_styles ``(project_id, name)`` UNIQUE 与 IntegrityError 兜底测试。

覆盖 alembic 0022 在 DB 层加的 ``UNIQUE (_scope_key, name)`` 约束 +
service 层 ``create_project_subtitle_style`` / ``update_project_subtitle_style``
的 ``IntegrityError → HTTP 409`` 兜底。

3 个 case：

1. cross-scope 同 name 可共存：
   - 系统级行（``project_id=NULL``）+ 项目级行（``project_id='proj-1'``）
   - 同 ``name='douyin_default'`` 应能并存
   - DB 层映射到 ``_scope_key='__system__'`` vs ``_scope_key='proj-1'``

2. 同 scope 重 name 拒绝（service 层 SELECT 命中 → 409）：
   - 同一 ``project_id`` 重复 name 在 SELECT 阶段就被拦下

3. IntegrityError → 409 兜底（绕过 service SELECT 模拟并发 race）：
   - 直接 raw INSERT 一条同 ``(project_id, name)`` 行
   - 再调 ``create_project_subtitle_style`` 触发 DB UNIQUE 约束
   - 必须转换为 HTTPException(409)，不能漏出 IntegrityError
"""

# pylint: disable=redefined-outer-name

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# 必须 import 全部模型，确保 Base.metadata 拥有完整 schema。
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
from app.models.studio_projects import Project
from app.schemas.commerce.subtitle_styles import (
    ProjectSubtitleStyleCreateInput,
)
from app.services.commerce.subtitle_styles import (
    create_project_subtitle_style,
)


_BASE_STYLE_PAYLOAD: dict[str, object] = {
    "name": "douyin_default",
    "description": "",
    "language_code": "zh-CN",
    "format": "ass",
    "font_family": "Source Han Sans CN Heavy",
    "font_fallback_chain": [],
    "font_size": 60,
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
}


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    """构造 file-backed SQLite 引擎并应用 alembic 0022 的生成列 + UNIQUE 索引。

    走 ``Base.metadata.create_all`` 不会带上 alembic 0022 的生成列；本
    fixture 在 ORM schema 之上手动追加生成列与 UNIQUE 索引，让 DB 层兜
    底测试能真正命中 ``IntegrityError`` 路径。
    """
    db_path = tmp_path / "subtitle-styles-unique.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}", future=True
    )
    session_local = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                "ALTER TABLE subtitle_styles ADD COLUMN _scope_key "
                "VARCHAR(64) GENERATED ALWAYS AS "
                "(COALESCE(project_id, '__system__')) STORED"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX uq_subtitle_styles_scope_name "
                "ON subtitle_styles (_scope_key, name)"
            )
        )
    yield session_local
    await engine.dispose()


async def _seed_project(session: AsyncSession, project_id: str) -> None:
    """建一条最小可用的 ``Project`` 行（FK 引用前置条件）。"""
    project = Project(
        id=project_id,
        name=f"Project {project_id}",
        description="",
        style="modern",
    )
    session.add(project)
    await session.flush()


# ---------------------------------------------------------------------------
# Case 1: cross-scope 同 name 可共存
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_system_and_project_scope_can_share_name(session_factory) -> None:
    """系统级 NULL + 项目级行同 name 可并存（两个不同 scope_key）。"""
    async with session_factory() as session:
        await _seed_project(session, "proj-1")
        # 模拟系统级 seed 行：raw INSERT，project_id NULL
        await session.execute(
            text(
                "INSERT INTO subtitle_styles "
                "(id, name, description, language_code, format, font_family, "
                " font_fallback_chain, font_size, primary_colour, "
                " secondary_colour, outline_colour, back_colour, bold, italic, "
                " border_style, outline, shadow, alignment, margin_l, margin_r, "
                " margin_v, play_res_x, play_res_y, is_system, sort_order, "
                " project_id, created_at, updated_at) "
                "VALUES "
                "('sys_douyin', 'douyin_default', '', 'zh-CN', 'ass', "
                " 'Source Han Sans CN Heavy', '[]', 60, '&H00FFFFFF', "
                " '&H00FFFFFF', '&H00000000', '&H80000000', 1, 0, 1, 3.0, 1.0, "
                " 'bottom_center', 60, 60, 200, 1080, 1920, 1, 0, NULL, "
                " '2026-05-29 00:00:00', '2026-05-29 00:00:00')"
            )
        )
        await session.commit()

        # 项目级同 name 必须能创建成功
        payload = ProjectSubtitleStyleCreateInput(**_BASE_STYLE_PAYLOAD)
        result = await create_project_subtitle_style(
            session, project_id="proj-1", payload=payload
        )
        await session.commit()
        assert result["name"] == "douyin_default"
        assert result["project_id"] == "proj-1"


# ---------------------------------------------------------------------------
# Case 2: 同 scope 重 name 拒绝（service SELECT 命中）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_scope_duplicate_name_rejected_by_select(
    session_factory,
) -> None:
    """同 project_id 重 name 时 service SELECT 命中 → HTTPException(409)。"""
    async with session_factory() as session:
        await _seed_project(session, "proj-1")
        payload = ProjectSubtitleStyleCreateInput(**_BASE_STYLE_PAYLOAD)
        await create_project_subtitle_style(
            session, project_id="proj-1", payload=payload
        )
        await session.commit()

        with pytest.raises(HTTPException) as exc_info:
            await create_project_subtitle_style(
                session, project_id="proj-1", payload=payload
            )
        assert exc_info.value.status_code == 409
        assert "already exists" in str(exc_info.value.detail).lower()


# ---------------------------------------------------------------------------
# Case 3: IntegrityError 兜底（绕过 SELECT 模拟并发 race）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_integrity_error_translates_to_409(session_factory) -> None:
    """绕过 service SELECT 直接 raw INSERT 制造 race，DB UNIQUE 兜底转 409。

    模拟逻辑：
        - 第一个 session 已经 raw INSERT 了项目级行（绕过 service SELECT）；
        - 第二个 session 走 ``create_project_subtitle_style``：SELECT 命中
          会先抛 409；为了真正命中 IntegrityError 路径，先 mock 让 SELECT
          看不到那条行——这里通过 ``DELETE → 重建`` 不可行，更直接的做
          法是：在事务 A 已经 add 但未 flush 时启动事务 B，但 SQLite
          + asyncio 跨连接难以可靠做到。
        - 退而求其次：直接调用 ``db.flush()`` 后立刻再 ``add`` 一条相同
          ``(project_id, name)`` 的 SubtitleStyle，触发 ``IntegrityError``，
          然后断言 ``create_project_subtitle_style`` 在内部 catch 它并转
          409。

    实现方式：
        把 service 内 ``_find_project_style_by_name`` monkeypatch 成
        ``return None``——直接跳过 SELECT 早返回，走到 ``db.flush()``
        触发 DB UNIQUE 约束抛 ``IntegrityError``，service 层 catch 后转
        HTTP 409。
    """
    async with session_factory() as session:
        await _seed_project(session, "proj-1")
        payload = ProjectSubtitleStyleCreateInput(**_BASE_STYLE_PAYLOAD)
        await create_project_subtitle_style(
            session, project_id="proj-1", payload=payload
        )
        await session.commit()

        # 通过 monkeypatch 让 service 内 SELECT 看不见已存在行
        from app.services.commerce import subtitle_styles as svc_mod

        async def _always_none(_db, *, project_id, name):  # noqa: ARG001
            return None

        original = svc_mod._find_project_style_by_name  # pylint: disable=protected-access
        svc_mod._find_project_style_by_name = _always_none  # type: ignore[assignment]
        try:
            with pytest.raises(HTTPException) as exc_info:
                await create_project_subtitle_style(
                    session, project_id="proj-1", payload=payload
                )
            assert exc_info.value.status_code == 409
            assert "already exists" in str(exc_info.value.detail).lower()
        finally:
            svc_mod._find_project_style_by_name = original  # type: ignore[assignment]
