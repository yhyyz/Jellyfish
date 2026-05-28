"""BrandStyleGuideService 单元测试 —— W25-T3。

覆盖 ≥3 个核心契约：

1. ``upsert`` 在该商品尚无规范时新建一行（returns ``created=True``）；
2. ``upsert`` 在该商品已有规范时部分更新（returns ``created=False``，未传
   字段保持原值）；
3. ``patch`` 在规范不存在时返回 404（与 upsert 区分）；
4. ``delete`` 删除已存在规范，再次 ``get`` 返回 404；
5. ``get`` / ``upsert`` / ``patch`` / ``delete`` 在 product 不存在时统一抛
   404 ``Product``。
"""

# pylint: disable=invalid-name

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.models  # noqa: F401  pylint: disable=unused-import
import app.models.brand_style_guide  # noqa: F401  pylint: disable=unused-import
import app.models.commerce_assets  # noqa: F401  pylint: disable=unused-import

from app.core.db import Base
from app.models.commerce_assets import Product
from app.services.commerce.brand_style_guide_service import (
    BrandStyleGuideService,
)


@asynccontextmanager
async def _build_session() -> AsyncGenerator[AsyncSession, None]:
    """构建一个干净的 in-memory SQLite 会话。"""
    engine: AsyncEngine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", future=True
    )
    session_local = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        async with session_local() as session:
            yield session
    finally:
        await engine.dispose()


async def _seed_product(session: AsyncSession, product_id: str) -> None:
    """在测试数据库中插入一条最小可用的 Product 行。"""
    session.add(
        Product(
            id=product_id,
            name=f"product-{product_id}",
            style="真人都市",
            visual_style="现实",
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_upsert_creates_when_absent() -> None:
    """商品尚无规范 → upsert 创建新行，返回 created=True。"""
    async with _build_session() as session:
        await _seed_product(session, "p1")
        service = BrandStyleGuideService(session)

        payload, created = await service.upsert(
            "p1",
            {
                "forced_phrases": ["买它"],
                "banned_patterns": [],
                "required_endings": ["立即下单"],
                "brand_persona_tagline": "理性消费",
            },
        )

        assert created is True
        assert payload["product_id"] == "p1"
        assert payload["forced_phrases"] == ["买它"]
        assert payload["required_endings"] == ["立即下单"]
        assert payload["brand_persona_tagline"] == "理性消费"
        assert isinstance(payload["id"], str) and payload["id"]


@pytest.mark.asyncio
async def test_upsert_updates_when_present() -> None:
    """商品已有规范 → 第二次 upsert 视为部分更新，未传字段保持原值。"""
    async with _build_session() as session:
        await _seed_product(session, "p2")
        service = BrandStyleGuideService(session)

        await service.upsert(
            "p2",
            {
                "forced_phrases": ["limited"],
                "banned_patterns": ["never lose"],
                "required_endings": ["dial now"],
                "brand_persona_tagline": "v1",
            },
        )

        # 第二次仅传两个字段，其它应保持原值
        payload, created = await service.upsert(
            "p2",
            {
                "forced_phrases": ["买它", "立享"],
                "brand_persona_tagline": "v2",
            },
        )

        assert created is False, "已有规范时应返回 created=False"
        assert payload["forced_phrases"] == ["买它", "立享"]
        assert payload["brand_persona_tagline"] == "v2"
        # 未传的字段保持原值
        assert payload["banned_patterns"] == ["never lose"]
        assert payload["required_endings"] == ["dial now"]


@pytest.mark.asyncio
async def test_patch_404_when_guide_absent() -> None:
    """规范不存在 → PATCH 返回 404 BrandStyleGuide（不自动创建）。"""
    async with _build_session() as session:
        await _seed_product(session, "p3")
        service = BrandStyleGuideService(session)

        with pytest.raises(HTTPException) as exc_info:
            await service.patch("p3", {"forced_phrases": ["x"]})

        assert exc_info.value.status_code == 404
        assert "BrandStyleGuide" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_delete_then_get_404() -> None:
    """delete 删除已存在规范后，再次 get 返回 404。"""
    async with _build_session() as session:
        await _seed_product(session, "p4")
        service = BrandStyleGuideService(session)

        await service.upsert("p4", {"forced_phrases": ["x"]})
        # 删除前先确认存在
        existing = await service.get("p4")
        assert existing["product_id"] == "p4"

        await service.delete("p4")

        with pytest.raises(HTTPException) as exc_info:
            await service.get("p4")
        assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_404_when_product_missing() -> None:
    """商品不存在时 → 所有方法统一抛 404 Product。"""
    async with _build_session() as session:
        service = BrandStyleGuideService(session)

        for action in (
            lambda: service.get("missing"),
            lambda: service.upsert("missing", {"forced_phrases": ["x"]}),
            lambda: service.patch("missing", {"forced_phrases": ["x"]}),
            lambda: service.delete("missing"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await action()
            assert exc_info.value.status_code == 404
            assert "Product" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_upsert_normalizes_none_to_default() -> None:
    """upsert 接受 None 值时把它们规范化为空数组 / 空串（创建路径）。"""
    async with _build_session() as session:
        await _seed_product(session, "p5")
        service = BrandStyleGuideService(session)

        # 全部字段使用 None
        payload, created = await service.upsert(
            "p5",
            {
                "forced_phrases": None,
                "banned_patterns": None,
                "required_endings": None,
                "brand_persona_tagline": None,
            },
        )

        assert created is True
        assert payload["forced_phrases"] == []
        assert payload["banned_patterns"] == []
        assert payload["required_endings"] == []
        assert payload["brand_persona_tagline"] == ""
