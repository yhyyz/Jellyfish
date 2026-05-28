"""``bootstrap_platform_export_presets`` 的功能性测试（W23-T1，P4 Wave A）。

覆盖目标：
1. 全量插入：fresh DB 上首次运行写入 5 行 ``is_system=True`` 系统预设；
2. 幂等：第二次运行 inserted=0、updated=0、unchanged=5；
3. 内容回滚：手工改写一行（name / aspect_ratio）后再次运行，会被纠回
   canonical 值；
4. 5 个预设的 platform / aspect_ratio / max_duration_sec 与任务规范
   完全一致：
   - douyin_default       9:16 / 60s
   - kuaishou_default     9:16 / 57s
   - xiaohongshu_default  1:1  / 60s
   - youtube_shorts_default 9:16 / 59s
   - tiktok_default       9:16 / 60s
5. 全部 ``is_system=True`` 且 sort_order 单调递增（0/10/20/30/40）。
"""

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
from app.models.platform_export_preset import PlatformExportPreset
from app.models.types import Platform
from app.services.commerce.bootstrap_export_presets import (
    bootstrap_platform_export_presets,
)


_EXPECTED_TOTAL = 5

# 与任务规格逐字对齐的预期值；本测试是该 spec 的可执行契约副本。
_EXPECTED_SPEC: dict[str, tuple[str, str, int]] = {
    "douyin_default": (Platform.douyin.value, "9:16", 60),
    "kuaishou_default": (Platform.kuaishou.value, "9:16", 57),
    "xiaohongshu_default": (Platform.xiaohongshu.value, "1:1", 60),
    "youtube_shorts_default": (Platform.youtube.value, "9:16", 59),
    "tiktok_default": (Platform.tiktok.value, "9:16", 60),
}


async def _build_session() -> tuple[AsyncSession, AsyncEngine]:
    """创建一个内存 SQLite 异步 session，并建好 ORM 表。"""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return session_local(), engine


def _platform_value(value: object) -> str:
    """容忍 SQLite str / MySQL Enum 两种回值，统一比较 ``.value``。"""

    if isinstance(value, Platform):
        return value.value
    return str(value)


@pytest.mark.asyncio
async def test_bootstrap_inserts_all_five_presets() -> None:
    """首次 seed 应写入 5 行 is_system=True 系统预设。"""

    db, engine = await _build_session()
    async with db:
        stats = await bootstrap_platform_export_presets(db)
        rows = (
            await db.execute(
                select(PlatformExportPreset).where(
                    PlatformExportPreset.is_system.is_(True)
                )
            )
        ).scalars().all()

    await engine.dispose()

    assert stats == {"inserted": _EXPECTED_TOTAL, "updated": 0, "unchanged": 0}
    assert len(rows) == _EXPECTED_TOTAL

    by_id = {row.id: row for row in rows}
    assert set(by_id) == set(_EXPECTED_SPEC), (
        f"系统预设 id 集合不一致：{set(by_id)} vs {set(_EXPECTED_SPEC)}"
    )

    for preset_id, (platform_value, aspect_ratio, max_duration_sec) in _EXPECTED_SPEC.items():
        row = by_id[preset_id]
        assert _platform_value(row.platform) == platform_value, (
            f"{preset_id}.platform={row.platform} 不等于 {platform_value}"
        )
        assert row.aspect_ratio == aspect_ratio, (
            f"{preset_id}.aspect_ratio={row.aspect_ratio} 不等于 {aspect_ratio}"
        )
        assert row.max_duration_sec == max_duration_sec, (
            f"{preset_id}.max_duration_sec={row.max_duration_sec} 不等于 {max_duration_sec}"
        )
        assert row.is_system is True
        assert row.file_format == "mp4"
        assert row.codec_preset == "h264_high_4_1"

    expected_sort_orders = {0, 10, 20, 30, 40}
    assert {row.sort_order for row in rows} == expected_sort_orders


@pytest.mark.asyncio
async def test_bootstrap_idempotent_after_second_run() -> None:
    """连续两次 seed：第二次必须 inserted=0、updated=0、unchanged=5；总行数仍然是 5。"""

    db, engine = await _build_session()
    async with db:
        first = await bootstrap_platform_export_presets(db)
        second = await bootstrap_platform_export_presets(db)
        rows_count = len(
            (
                await db.execute(select(PlatformExportPreset))
            ).scalars().all()
        )
    await engine.dispose()

    assert first == {"inserted": _EXPECTED_TOTAL, "updated": 0, "unchanged": 0}
    assert second == {"inserted": 0, "updated": 0, "unchanged": _EXPECTED_TOTAL}
    assert rows_count == _EXPECTED_TOTAL


@pytest.mark.asyncio
async def test_bootstrap_restores_mutated_row() -> None:
    """手工改写一行 name / aspect_ratio 后再次 seed：应有 1 条 updated，
    被改坏的字段会被纠回 canonical 值。"""

    db, engine = await _build_session()
    async with db:
        await bootstrap_platform_export_presets(db)

        target_id = "douyin_default"
        target = await db.get(PlatformExportPreset, target_id)
        assert target is not None
        original_name = target.name
        original_aspect = target.aspect_ratio
        target.name = "MUTATED"
        target.aspect_ratio = "16:9"
        await db.commit()

        stats = await bootstrap_platform_export_presets(db)
        restored = await db.get(PlatformExportPreset, target_id)

    await engine.dispose()

    assert stats == {
        "inserted": 0,
        "updated": 1,
        "unchanged": _EXPECTED_TOTAL - 1,
    }
    assert restored is not None
    assert restored.name == original_name
    assert restored.aspect_ratio == original_aspect


@pytest.mark.asyncio
async def test_bootstrap_three_runs_still_five_rows() -> None:
    """跑 3 次 bootstrap，表内仍然只有 5 行（强幂等）。"""

    db, engine = await _build_session()
    async with db:
        await bootstrap_platform_export_presets(db)
        await bootstrap_platform_export_presets(db)
        await bootstrap_platform_export_presets(db)
        rows = (
            await db.execute(select(PlatformExportPreset))
        ).scalars().all()
    await engine.dispose()

    assert len(rows) == _EXPECTED_TOTAL
