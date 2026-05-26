"""``bootstrap_builtin_subtitle_styles`` 的功能性测试（P3 W18）。

覆盖目标：
1. 全量插入：fresh DB 上首次运行写入 3 行 ``is_system=True`` 字幕样式；
2. 幂等：第二次运行不再有 inserts，且 ``unchanged == 3``；
3. 内容回滚：手工改写一行（name + font_size）后再次运行，会被纠回 canonical；
4. 3 个内置 ID 与 W18 plan 约定一致：``douyin_default`` / ``tiktok_viral`` /
   ``reels_lower_third``。
"""

# pylint: disable=redefined-outer-name

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.db import Base
from app.models.subtitle import SubtitleStyle
from app.services.studio.builtin_subtitle_styles import (
    bootstrap_builtin_subtitle_styles,
)


_EXPECTED_TOTAL = 3

_BUILTIN_STYLE_IDS = {
    "douyin_default",
    "tiktok_viral",
    "reels_lower_third",
}


async def _build_session() -> tuple[AsyncSession, AsyncEngine]:
    """创建一个内存 SQLite 异步 session，并建好 ORM 表。"""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return session_local(), engine


# ---------------------------------------------------------------------------
# 1. 全量插入
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bootstrap_inserts_all_three_subtitle_styles() -> None:
    """首次 seed 应写入 3 行 ``is_system=True`` 字幕样式。"""

    db, engine = await _build_session()
    async with db:
        stats = await bootstrap_builtin_subtitle_styles(db)
        rows = (
            await db.execute(
                select(SubtitleStyle).where(SubtitleStyle.is_system.is_(True))
            )
        ).scalars().all()

    await engine.dispose()

    assert stats == {"inserted": _EXPECTED_TOTAL, "updated": 0, "unchanged": 0}
    assert len(rows) == _EXPECTED_TOTAL
    assert {row.id for row in rows} == _BUILTIN_STYLE_IDS


# ---------------------------------------------------------------------------
# 2. 幂等
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bootstrap_idempotent_on_second_run() -> None:
    """第二次运行：不再 INSERT，全部 unchanged。"""

    db, engine = await _build_session()
    async with db:
        await bootstrap_builtin_subtitle_styles(db)
        stats_second = await bootstrap_builtin_subtitle_styles(db)

    await engine.dispose()

    assert stats_second == {
        "inserted": 0,
        "updated": 0,
        "unchanged": _EXPECTED_TOTAL,
    }


# ---------------------------------------------------------------------------
# 3. 内容回滚
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bootstrap_rolls_back_manual_changes() -> None:
    """手工改写 name + font_size 后再次 seed，应被纠回 canonical。"""

    db, engine = await _build_session()
    async with db:
        await bootstrap_builtin_subtitle_styles(db)

        # 手工改写 douyin_default：name 改成短名，font_size 改成 12（违法值）。
        douyin = await db.get(SubtitleStyle, "douyin_default")
        assert douyin is not None
        douyin.name = "已被人工修改"
        douyin.font_size = 12
        await db.commit()

        stats = await bootstrap_builtin_subtitle_styles(db)

        # 再读：name 与 font_size 应被纠回。
        douyin_after = await db.get(SubtitleStyle, "douyin_default")

    await engine.dispose()

    assert stats["updated"] == 1
    assert stats["unchanged"] == _EXPECTED_TOTAL - 1
    assert stats["inserted"] == 0
    assert douyin_after is not None
    assert douyin_after.name == "抖音默认"
    assert douyin_after.font_size == 64


# ---------------------------------------------------------------------------
# 4. 系统级标记 + 排序契约
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bootstrap_marks_all_as_system_with_ascending_sort_order() -> None:
    """3 个内置样式都应是 ``is_system=True``，sort_order 0/10/20 递增。"""

    db, engine = await _build_session()
    async with db:
        await bootstrap_builtin_subtitle_styles(db)
        rows = (
            await db.execute(
                select(SubtitleStyle).order_by(SubtitleStyle.sort_order)
            )
        ).scalars().all()

    await engine.dispose()

    assert [r.id for r in rows] == [
        "douyin_default",
        "tiktok_viral",
        "reels_lower_third",
    ]
    assert [r.sort_order for r in rows] == [0, 10, 20]
    assert all(r.is_system for r in rows)


# ---------------------------------------------------------------------------
# 5. 字体回退链非空
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bootstrap_populates_font_fallback_chain_for_each_style() -> None:
    """每个内置样式的 ``font_fallback_chain`` 应非空，至少含主 family。"""

    db, engine = await _build_session()
    async with db:
        await bootstrap_builtin_subtitle_styles(db)
        rows = (
            await db.execute(select(SubtitleStyle))
        ).scalars().all()

    await engine.dispose()

    for row in rows:
        chain = row.font_fallback_chain or []
        assert len(chain) >= 2, f"{row.id} font_fallback_chain too short: {chain}"
        # 主 family 必须出现在 fallback chain 第一项。
        assert chain[0] == row.font_family
