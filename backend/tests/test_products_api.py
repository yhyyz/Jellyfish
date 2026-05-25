"""W6-T1: ``/api/v1/studio/products`` 端到端 TestClient 测试。

测试策略
--------

- 使用文件型 SQLite + ``Base.metadata.create_all`` 建表，覆盖
  ``products`` / ``product_images`` / ``project_product_links`` 等模型；
- 通过 SQLAlchemy ``connect`` 事件开启 ``PRAGMA foreign_keys = ON``，
  让 ``ON DELETE CASCADE`` 在 SQLite 中真正生效（默认是关闭的），
  以验证 ``Product`` 删除时 ``ProductImage`` / ``ProjectProductLink`` 级联清理；
- 通过 ``app.dependency_overrides`` 覆盖 ``get_db``，让路由命中测试库；
- 每个测试用例独立 ``tmp_path`` 文件，避免跨用例数据残留。

覆盖点
------

1. 列表：空 DB 返回分页空 envelope
2. 创建：返回 201 + ApiResponse
3. 创建冲突：name 唯一约束 → 409
4. 创建：未传 id 自动生成
5. 详情：含 images 列表
6. 详情：404
7. 更新：仅改 name，brand 保持不变
8. 更新：404
9. 删除：返回 204 并级联清理 images
10. 删除：404
11. 加图：返回 201
12. 加图：(quality, angle) 重复 → 409
13. 删图：返回 204
14. 列表：按 category 过滤
15. 列表：按 name 子串模糊匹配
"""

# pylint: disable=redefined-outer-name

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.db import Base
from app.dependencies import get_db
from app.main import app
from app.models.studio import FileItem
from app.models.types import (
    AssetQualityLevel,
    AssetViewAngle,
    FileType,
    ProductCategory,
    ProjectStyle,
    ProjectVisualStyle,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def session_local(tmp_path) -> Generator[async_sessionmaker[AsyncSession], None, None]:
    """构建一次性 SQLite 测试会话工厂；开启 SQLite 外键以验证 CASCADE。"""
    db_path = tmp_path / "products-api.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_fk(dbapi_conn, _conn_record) -> None:  # pragma: no cover - hook
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON")
        cur.close()

    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _create_all() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    try:
        yield sm
    finally:
        async def _dispose() -> None:
            await engine.dispose()

        asyncio.run(_dispose())


@pytest.fixture
def client_with_db(session_local) -> Generator[TestClient, None, None]:
    """覆盖 ``get_db`` 让 FastAPI 路由用测试库；测试结束自动 cleanup。"""

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_local() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_BASE_BODY: dict[str, object] = {
    "name": "测试商品 A",
    "brand": "Test Brand",
    "category": ProductCategory.beauty.value,
    "description": "示例商品",
    "selling_points": ["卖点 1"],
    "target_audience": {"age_range": "18-25"},
    "catchphrases": ["金句"],
    "competitor_names": ["竞品 X"],
    "visual_style": ProjectVisualStyle.live_action.value,
    "style": ProjectStyle.real_people_city.value,
}


def _make_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = dict(_BASE_BODY)
    body.update(overrides)
    return body


def _create(client: TestClient, **overrides: object) -> dict[str, object]:
    resp = client.post("/api/v1/studio/products", json=_make_body(**overrides))
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def _seed_files(session_local, file_ids: list[str]) -> None:
    """预置 ``files`` 行，避免 ``ProductImage.file_id`` 外键校验失败。

    SQLite 默认外键关闭、但本测试用例 fixture 显式 ``PRAGMA foreign_keys = ON``，
    因此必须先有 ``FileItem`` 才能写 ``ProductImage``。
    """

    async def _seed() -> None:
        async with session_local() as db:
            for fid in file_ids:
                db.add(
                    FileItem(
                        id=fid,
                        type=FileType.image,
                        name=fid,
                        thumbnail="",
                        tags=[],
                        storage_key=f"files/{fid}.png",
                    )
                )
            await db.commit()

    asyncio.run(_seed())


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


def test_list_products_returns_paginated_envelope(client_with_db: TestClient) -> None:
    resp = client_with_db.get("/api/v1/studio/products")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    assert body["data"]["items"] == []
    assert body["data"]["pagination"]["total"] == 0
    assert body["data"]["pagination"]["page"] == 1


def test_create_product_returns_201_with_envelope(client_with_db: TestClient) -> None:
    resp = client_with_db.post(
        "/api/v1/studio/products",
        json=_make_body(id="prod-001", name="新商品 X"),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["code"] == 201
    assert body["message"] == "success"
    assert body["data"]["id"] == "prod-001"
    assert body["data"]["name"] == "新商品 X"
    assert body["data"]["category"] == ProductCategory.beauty.value
    assert body["data"]["images"] == []


def test_create_product_with_duplicate_name_returns_409(
    client_with_db: TestClient,
) -> None:
    _create(client_with_db, id="prod-dup-1", name="重复商品")
    resp = client_with_db.post(
        "/api/v1/studio/products",
        json=_make_body(id="prod-dup-2", name="重复商品"),
    )
    assert resp.status_code == 409
    assert resp.json() == {
        "code": 409,
        "message": "Product already exists",
        "data": None,
        "meta": None,
    }


def test_create_product_auto_generates_id_when_omitted(
    client_with_db: TestClient,
) -> None:
    resp = client_with_db.post(
        "/api/v1/studio/products",
        json=_make_body(name="自动 ID 商品"),
    )
    assert resp.status_code == 201
    pid = resp.json()["data"]["id"]
    assert isinstance(pid, str)
    assert len(pid) == 32  # uuid4().hex 长度恒为 32


def test_get_product_returns_detail_with_images(
    client_with_db: TestClient,
    session_local,
) -> None:
    _seed_files(session_local, ["file-xyz"])
    created = _create(client_with_db, id="prod-detail", name="详情商品")
    img_resp = client_with_db.post(
        f"/api/v1/studio/products/{created['id']}/images",
        json={
            "file_id": "file-xyz",
            "quality_level": AssetQualityLevel.high.value,
            "view_angle": AssetViewAngle.front.value,
            "is_primary": True,
        },
    )
    assert img_resp.status_code == 201

    resp = client_with_db.get(f"/api/v1/studio/products/{created['id']}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == "prod-detail"
    assert len(data["images"]) == 1
    assert data["images"][0]["file_id"] == "file-xyz"
    assert data["images"][0]["quality_level"] == AssetQualityLevel.high.value
    assert data["images"][0]["view_angle"] == AssetViewAngle.front.value
    assert data["images"][0]["is_primary"] is True


def test_get_product_404_when_missing(client_with_db: TestClient) -> None:
    resp = client_with_db.get("/api/v1/studio/products/missing-id")
    assert resp.status_code == 404
    assert resp.json() == {
        "code": 404,
        "message": "Product not found",
        "data": None,
        "meta": None,
    }


def test_update_product_partial_only_changes_provided_fields(
    client_with_db: TestClient,
) -> None:
    created = _create(client_with_db, id="prod-patch", name="原名", brand="原品牌")
    resp = client_with_db.patch(
        f"/api/v1/studio/products/{created['id']}",
        json={"name": "新名"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["name"] == "新名"
    assert data["brand"] == "原品牌"


def test_update_product_404_when_missing(client_with_db: TestClient) -> None:
    resp = client_with_db.patch(
        "/api/v1/studio/products/missing-id",
        json={"name": "x"},
    )
    assert resp.status_code == 404
    assert resp.json()["message"] == "Product not found"


def test_delete_product_returns_204_and_cascades_images(
    client_with_db: TestClient,
    session_local,
) -> None:
    _seed_files(session_local, ["file-del"])
    created = _create(client_with_db, id="prod-del", name="待删商品")
    img_resp = client_with_db.post(
        f"/api/v1/studio/products/{created['id']}/images",
        json={
            "file_id": "file-del",
            "quality_level": AssetQualityLevel.medium.value,
            "view_angle": AssetViewAngle.front.value,
        },
    )
    assert img_resp.status_code == 201
    image_id = img_resp.json()["data"]["id"]

    del_resp = client_with_db.delete(f"/api/v1/studio/products/{created['id']}")
    assert del_resp.status_code == 204

    # product 已删
    assert (
        client_with_db.get(f"/api/v1/studio/products/{created['id']}").status_code == 404
    )

    # image 也被级联清理：再次尝试删该 image 必然 404
    re_del = client_with_db.delete(
        f"/api/v1/studio/products/{created['id']}/images/{image_id}"
    )
    assert re_del.status_code == 404


def test_delete_product_404_when_missing(client_with_db: TestClient) -> None:
    resp = client_with_db.delete("/api/v1/studio/products/missing-id")
    assert resp.status_code == 404
    assert resp.json()["message"] == "Product not found"


def test_add_product_image_returns_201_with_envelope(
    client_with_db: TestClient,
    session_local,
) -> None:
    _seed_files(session_local, ["file-1"])
    created = _create(client_with_db, id="prod-img", name="加图商品")
    resp = client_with_db.post(
        f"/api/v1/studio/products/{created['id']}/images",
        json={
            "file_id": "file-1",
            "quality_level": AssetQualityLevel.medium.value,
            "view_angle": AssetViewAngle.left.value,
            "width": 1024,
            "height": 1024,
            "fmt": "png",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["code"] == 201
    assert body["data"]["product_id"] == created["id"]
    assert body["data"]["file_id"] == "file-1"
    assert body["data"]["width"] == 1024
    assert body["data"]["fmt"] == "png"


def test_add_product_image_unique_constraint_violation(
    client_with_db: TestClient,
    session_local,
) -> None:
    _seed_files(session_local, ["file-a", "file-b"])
    created = _create(client_with_db, id="prod-img-uq", name="加图重复商品")
    payload = {
        "file_id": "file-a",
        "quality_level": AssetQualityLevel.medium.value,
        "view_angle": AssetViewAngle.front.value,
    }
    first = client_with_db.post(
        f"/api/v1/studio/products/{created['id']}/images",
        json=payload,
    )
    assert first.status_code == 201

    second = client_with_db.post(
        f"/api/v1/studio/products/{created['id']}/images",
        json={**payload, "file_id": "file-b"},
    )
    assert second.status_code == 409
    assert second.json()["message"] == "ProductImage already exists"


def test_delete_product_image_returns_204(
    client_with_db: TestClient,
    session_local,
) -> None:
    _seed_files(session_local, ["file-del-img"])
    created = _create(client_with_db, id="prod-img-del", name="删图商品")
    img_resp = client_with_db.post(
        f"/api/v1/studio/products/{created['id']}/images",
        json={
            "file_id": "file-del-img",
            "quality_level": AssetQualityLevel.medium.value,
            "view_angle": AssetViewAngle.right.value,
        },
    )
    image_id = img_resp.json()["data"]["id"]

    resp = client_with_db.delete(
        f"/api/v1/studio/products/{created['id']}/images/{image_id}"
    )
    assert resp.status_code == 204

    detail = client_with_db.get(f"/api/v1/studio/products/{created['id']}")
    assert detail.json()["data"]["images"] == []


def test_list_products_filter_by_category(client_with_db: TestClient) -> None:
    _create(
        client_with_db,
        id="prod-cat-beauty",
        name="美妆商品",
        category=ProductCategory.beauty.value,
    )
    _create(
        client_with_db,
        id="prod-cat-food",
        name="食品商品",
        category=ProductCategory.food.value,
    )
    resp = client_with_db.get(
        "/api/v1/studio/products",
        params={"category": ProductCategory.food.value},
    )
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["id"] == "prod-cat-food"


def test_list_products_search_by_name_substring(client_with_db: TestClient) -> None:
    _create(client_with_db, id="prod-search-1", name="独特关键词Alpha")
    _create(client_with_db, id="prod-search-2", name="另一个商品 Bravo")
    resp = client_with_db.get(
        "/api/v1/studio/products",
        params={"q": "Alpha"},
    )
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["id"] == "prod-search-1"
