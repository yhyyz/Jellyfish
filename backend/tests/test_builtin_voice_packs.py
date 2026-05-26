"""``bootstrap_builtin_voice_packs`` 的功能性测试（P3 W17）。

覆盖目标：
1. 全量插入：fresh DB 上首次运行写入 6 行 ``is_system=True`` 音色包；
2. 幂等：第二次运行不再有 inserts，且 ``unchanged == 6``；
3. 内容回滚：手工改写一行（name）后再次运行，会被纠回 canonical；
4. 6 个 voice id 与官方 DashScope 列表精确一致（含 longxiaochun 的
   ``_v2`` 后缀，其余 5 个不带）。
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
from app.models.types import VoiceGender, VoiceProvider
from app.models.voice_pack import VoicePack
from app.services.studio.builtin_voice_packs import bootstrap_builtin_voice_packs


# 预期数量：6 个 zh-CN cosyvoice-v2 内置音色包。
_EXPECTED_TOTAL = 6


# 官方 DashScope cosyvoice-v2 voice id 一一对应；
# 唯一带 ``_v2`` 后缀的是 longxiaochun，这是平台现状，不可改写。
_OFFICIAL_VOICE_IDS = {
    "cosyvoice_v2_longxiaochun": "longxiaochun_v2",
    "cosyvoice_v2_longanlang": "longanlang",
    "cosyvoice_v2_longanwen": "longanwen",
    "cosyvoice_v2_longniuniu": "longniuniu",
    "cosyvoice_v2_longsanshu": "longsanshu",
    "cosyvoice_v2_longlaobo": "longlaobo",
}


# ---------------------------------------------------------------------------
# 测试基础设施
# ---------------------------------------------------------------------------


async def _build_session() -> tuple[AsyncSession, AsyncEngine]:
    """创建一个内存 SQLite 异步 session，并建好 ORM 表。"""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return session_local(), engine


# ---------------------------------------------------------------------------
# 1. 全量插入
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bootstrap_inserts_all_six_voice_packs() -> None:
    """首次 seed 应写入 6 行 is_system=True 音色包。"""

    db, engine = await _build_session()
    async with db:
        stats = await bootstrap_builtin_voice_packs(db)
        rows = (
            await db.execute(
                select(VoicePack).where(VoicePack.is_system.is_(True))
            )
        ).scalars().all()

    await engine.dispose()

    assert stats == {"inserted": _EXPECTED_TOTAL, "updated": 0, "unchanged": 0}
    assert len(rows) == _EXPECTED_TOTAL

    # provider 与 language 全部固定为 cosyvoice + zh-CN。
    for row in rows:
        assert row.is_system is True
        assert row.language_code == "zh-CN"
        # provider 列在 SQLite 上回成 str，在 MySQL 上回成 Enum；都比 .value。
        provider_value = (
            row.provider.value
            if isinstance(row.provider, VoiceProvider)
            else str(row.provider)
        )
        assert provider_value == VoiceProvider.aliyun_cosyvoice.value
        assert row.default_speed == 1.0

    # sort_order 至少覆盖到 50（老者档），且单调递增的 6 档全部出现。
    expected_sort_orders = {0, 10, 20, 30, 40, 50}
    assert {row.sort_order for row in rows} == expected_sort_orders


# ---------------------------------------------------------------------------
# 2. 幂等
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bootstrap_idempotent() -> None:
    """连续两次 seed：第二次必须 inserted=0、updated=0、unchanged=6。"""

    db, engine = await _build_session()
    async with db:
        first = await bootstrap_builtin_voice_packs(db)
        second = await bootstrap_builtin_voice_packs(db)
    await engine.dispose()

    assert first == {"inserted": _EXPECTED_TOTAL, "updated": 0, "unchanged": 0}
    assert second == {"inserted": 0, "updated": 0, "unchanged": _EXPECTED_TOTAL}


# ---------------------------------------------------------------------------
# 3. 内容回滚
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bootstrap_updates_changed_row_back_to_canonical() -> None:
    """手工改写一行 name 后再次 seed：应有 1 条 updated，5 条 unchanged，
    且被改坏的 name 被纠回 canonical 值。"""

    db, engine = await _build_session()
    async with db:
        await bootstrap_builtin_voice_packs(db)

        # 选定一条已知 id 改名，模拟“运营手抖”。
        target_id = "cosyvoice_v2_longanlang"
        target = await db.get(VoicePack, target_id)
        assert target is not None
        original_name = target.name
        target.name = "MUTATED-NAME"
        await db.commit()

        stats = await bootstrap_builtin_voice_packs(db)

        restored = await db.get(VoicePack, target_id)

    await engine.dispose()

    assert stats == {
        "inserted": 0,
        "updated": 1,
        "unchanged": _EXPECTED_TOTAL - 1,
    }
    assert restored is not None
    assert restored.name == original_name
    assert restored.name != "MUTATED-NAME"


# ---------------------------------------------------------------------------
# 4. 官方 voice id 一致性（含 _v2 后缀差异）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_voice_ids_match_official_dashscope_list() -> None:
    """6 个 provider_voice_id 必须与 DashScope 官方音色清单逐字一致：
    - longxiaochun 必须带 ``_v2`` 后缀；
    - 其余 5 个（longanlang / longanwen / longniuniu / longsanshu /
      longlaobo）必须 **不** 带后缀。
    """

    db, engine = await _build_session()
    async with db:
        await bootstrap_builtin_voice_packs(db)
        rows = (
            await db.execute(
                select(VoicePack).where(VoicePack.is_system.is_(True))
            )
        ).scalars().all()
    await engine.dispose()

    actual = {row.id: row.provider_voice_id for row in rows}
    assert actual == _OFFICIAL_VOICE_IDS

    # 后缀差异硬断言：仅 longxiaochun 带 _v2。
    assert actual["cosyvoice_v2_longxiaochun"].endswith("_v2")
    for non_v2_id in (
        "cosyvoice_v2_longanlang",
        "cosyvoice_v2_longanwen",
        "cosyvoice_v2_longniuniu",
        "cosyvoice_v2_longsanshu",
        "cosyvoice_v2_longlaobo",
    ):
        assert not actual[non_v2_id].endswith("_v2"), (
            f"{non_v2_id} 不应带 _v2 后缀（官方音色 id 不带）"
        )


# ---------------------------------------------------------------------------
# 5. 性别 / archetype_hint 元数据正确性
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gender_and_archetype_hint_metadata() -> None:
    """gender 与 archetype_hint 必须按 spec 写入：
    - 中性档（longxiaochun）-> neutral，hint=sage
    - 女声档（longanwen）-> female
    - 童声档（longniuniu）-> child
    - 中年男（longsanshu）-> male，hint=expert
    - 老者（longlaobo）-> male，hint=sage
    """

    db, engine = await _build_session()
    async with db:
        await bootstrap_builtin_voice_packs(db)

        def _gender_value(value: object) -> str:
            return value.value if isinstance(value, VoiceGender) else str(value)

        xiaochun = await db.get(VoicePack, "cosyvoice_v2_longxiaochun")
        anwen = await db.get(VoicePack, "cosyvoice_v2_longanwen")
        niuniu = await db.get(VoicePack, "cosyvoice_v2_longniuniu")
        sanshu = await db.get(VoicePack, "cosyvoice_v2_longsanshu")
        laobo = await db.get(VoicePack, "cosyvoice_v2_longlaobo")

        assert xiaochun is not None
        assert anwen is not None
        assert niuniu is not None
        assert sanshu is not None
        assert laobo is not None

        assert _gender_value(xiaochun.gender) == VoiceGender.neutral.value
        assert xiaochun.archetype_hint == "sage"

        assert _gender_value(anwen.gender) == VoiceGender.female.value

        assert _gender_value(niuniu.gender) == VoiceGender.child.value

        assert _gender_value(sanshu.gender) == VoiceGender.male.value
        assert sanshu.archetype_hint == "expert"

        assert _gender_value(laobo.gender) == VoiceGender.male.value
        assert laobo.archetype_hint == "sage"

    await engine.dispose()
