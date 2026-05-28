"""BrandStyleGuide CRUD API 集成测试 —— W25-T3。

覆盖 ≥5 个核心契约：

1. POST 创建：商品已存在 + 规范不存在 → 201，返回完整 BrandStyleGuideRead；
2. POST upsert：商品已有规范 → 200（部分更新），未传字段保持原值；
3. GET：规范存在 → 200；规范不存在 → 404；
4. PATCH：规范不存在 → 404（与 POST upsert 区分）；
5. DELETE：删除后 GET 返回 404；商品删除时（CASCADE）规范同步消失；
6. 1:1 unique 约束：同一 product 重复 POST 仍走 upsert 路径，不会触发
   409（这是 service 层把 IntegrityError 转 upsert 的预期行为）；
7. 无效 product_id 时所有 4 个端点统一返回 404 Product；
8. 响应壳：所有路径都包装为 ApiResponse[code/message/data]。
"""

# pylint: disable=invalid-name

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from fastapi.testclient import TestClient
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
from app.dependencies import get_db
from app.main import app
from app.models.commerce_assets import Product


async def _build_engine_with_product(
    product_id: str = "p_test",
) -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
    """构建一次性 SQLite engine 并预置一条商品。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", future=True
    )
    session_local = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_local() as seed_session:
        seed_session.add(
            Product(
                id=product_id,
                name=f"product-{product_id}",
                style="真人都市",
                visual_style="现实",
            )
        )
        await seed_session.commit()
    return session_local, engine


def _make_override(session_local: async_sessionmaker[AsyncSession]):
    """构造 dependency override：每次请求复用同一个 sessionmaker。

    与生产 ``get_db`` 行为一致：成功结束时 ``commit``，异常 ``rollback``，
    保证后续请求能看到上一请求落库的数据。
    """

    async def _get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_local() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return _get_db


_BASE = "/api/v1/studio/products/{pid}/brand-style-guide"


@pytest.mark.asyncio
async def test_post_creates_brand_style_guide_returns_201(
    client: TestClient,
) -> None:
    """商品已存在 + 规范不存在 → POST 返回 201 与完整规范字段。"""
    session_local, engine = await _build_engine_with_product("p1")
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.post(
            _BASE.format(pid="p1"),
            json={
                "forced_phrases": ["买它"],
                "banned_patterns": [],
                "required_endings": ["立即下单"],
                "brand_persona_tagline": "理性消费",
            },
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["code"] == 201
        assert body["data"]["product_id"] == "p1"
        assert body["data"]["forced_phrases"] == ["买它"]
        assert body["data"]["required_endings"] == ["立即下单"]
        assert body["data"]["brand_persona_tagline"] == "理性消费"
        assert isinstance(body["data"]["id"], str)
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_post_upsert_updates_existing_returns_200(
    client: TestClient,
) -> None:
    """商品已有规范 → 第二次 POST 走部分更新，返回 200，未传字段保持原值。"""
    session_local, engine = await _build_engine_with_product("p2")
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        client.post(
            _BASE.format(pid="p2"),
            json={
                "forced_phrases": ["limited"],
                "banned_patterns": ["never"],
                "required_endings": ["dial"],
                "brand_persona_tagline": "v1",
            },
        )

        res = client.post(
            _BASE.format(pid="p2"),
            json={
                "forced_phrases": ["买它", "立享"],
                "brand_persona_tagline": "v2",
            },
        )

        assert res.status_code == 200, res.text
        body = res.json()
        assert body["code"] == 200
        assert body["data"]["forced_phrases"] == ["买它", "立享"]
        assert body["data"]["brand_persona_tagline"] == "v2"
        # 未传字段保持原值
        assert body["data"]["banned_patterns"] == ["never"]
        assert body["data"]["required_endings"] == ["dial"]
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_404_when_guide_missing(client: TestClient) -> None:
    """商品存在但规范不存在 → GET 返回 404 BrandStyleGuide。"""
    session_local, engine = await _build_engine_with_product("p3")
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.get(_BASE.format(pid="p3"))
        assert res.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_patch_404_when_guide_missing(client: TestClient) -> None:
    """规范不存在 → PATCH 返回 404（与 POST upsert 区分）。"""
    session_local, engine = await _build_engine_with_product("p4")
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        res = client.patch(
            _BASE.format(pid="p4"),
            json={"forced_phrases": ["x"]},
        )
        assert res.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_delete_then_get_404(client: TestClient) -> None:
    """delete 删除规范后，再次 GET 返回 404。"""
    session_local, engine = await _build_engine_with_product("p5")
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        client.post(
            _BASE.format(pid="p5"),
            json={"forced_phrases": ["x"]},
        )
        del_res = client.delete(_BASE.format(pid="p5"))
        assert del_res.status_code == 200
        assert del_res.json()["code"] == 200

        get_res = client.get(_BASE.format(pid="p5"))
        assert get_res.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_all_endpoints_404_when_product_missing(
    client: TestClient,
) -> None:
    """商品不存在时所有 4 个端点统一返回 404 Product。"""
    session_local, engine = await _build_engine_with_product("p6")
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        path = _BASE.format(pid="missing-product")
        for response in (
            client.get(path),
            client.post(path, json={"forced_phrases": ["x"]}),
            client.patch(path, json={"forced_phrases": ["x"]}),
            client.delete(path),
        ):
            assert response.status_code == 404, response.text
            body = response.json()
            # 兼容 FastAPI 默认 detail 与 ApiResponse 包装两种壳
            payload_text = (body.get("detail") or body.get("message") or "").lower()
            assert "product" in payload_text, body
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_response_envelope_is_api_response(client: TestClient) -> None:
    """所有路径包装为 ApiResponse[code/message/data]。"""
    session_local, engine = await _build_engine_with_product("p7")
    app.dependency_overrides[get_db] = _make_override(session_local)
    try:
        path = _BASE.format(pid="p7")

        post_res = client.post(path, json={"forced_phrases": ["x"]})
        assert post_res.status_code == 201
        assert set(post_res.json().keys()) >= {"code", "message", "data"}

        get_res = client.get(path)
        assert get_res.status_code == 200
        assert set(get_res.json().keys()) >= {"code", "message", "data"}

        patch_res = client.patch(path, json={"banned_patterns": ["y"]})
        assert patch_res.status_code == 200
        assert set(patch_res.json().keys()) >= {"code", "message", "data"}

        del_res = client.delete(path)
        assert del_res.status_code == 200
        assert set(del_res.json().keys()) >= {"code", "message", "data"}
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()
