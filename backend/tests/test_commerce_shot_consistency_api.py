"""``GET /api/v1/commerce/shots/{shot_id}/consistency-evidence`` API 单测（W27-T3）。

覆盖契约：

1. ``test_consistency_evidence_returns_score_and_status``：种入 Shot +
   Product + ProductImage(FRONT)，``consistency_score=0.92``，期望响应
   ``status="green"``，``reference_image_url`` / ``sampled_frame_urls``
   非空，``score`` 与种子一致。
2. ``test_returns_404_for_unknown_shot``：未知 shot_id → 404 +
   ``detail="Shot not found"``，envelope 形态正确。
3. ``test_includes_retry_count``：``retry_count`` 字段存在于响应中；
   T27-2 未落地时为 ``None``，已落地时透传 model 上的整数值。
4. ``test_status_unknown_when_score_is_null``：``consistency_score=None``
   时 status="unknown"，避免与 0.0 混淆。
5. ``test_status_amber_in_range_75_to_85``：边界值映射正确，确保前后端
   阈值同源。

测试策略：

- file-backed SQLite + ``Base.metadata.create_all`` 起完整 ORM；
- 通过 ``app.dependency_overrides`` 覆盖 ``get_db``；
- ``_build_public_url`` 使用项目默认 settings，无需 mock S3；测试只断
  言 URL 字段为非空字符串、不强校 host。
"""

# pylint: disable=redefined-outer-name

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.dependencies import get_db
from app.main import app
from app.models.commerce_assets import Product, ProductImage, ProjectProductLink
from app.models.studio import Chapter, FileItem, Project, Shot
from app.models.studio_shots import ShotStatus
from app.models.types import (
    AssetQualityLevel,
    AssetViewAngle,
    FileType,
    ProjectStyle,
)


@pytest.fixture
def session_local(tmp_path) -> Generator[async_sessionmaker[AsyncSession], None, None]:
    """文件型 SQLite + Base.metadata.create_all 的 async sessionmaker。

    与 ``test_commerce_tasks_api`` 使用同款 fixture，保证表结构齐全（含
    Shot / Product / ProductImage / ProjectProductLink）。
    """

    db_path = tmp_path / "shot-consistency.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
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


async def _seed_shot(
    db: AsyncSession,
    *,
    shot_id: str = "shot-1",
    consistency_score: float | None = 0.92,
    with_product: bool = True,
    with_reference: bool = True,
) -> None:
    """种入 Project + Chapter + Shot；可选挂 Product / ProductImage。"""

    db.add(
        Project(id="proj-1", name="测试项目", style=ProjectStyle.real_people_city)
    )
    db.add(Chapter(id="chap-1", project_id="proj-1", index=1, title="Ch1"))
    db.add(
        Shot(
            id=shot_id,
            chapter_id="chap-1",
            index=1,
            title="测试镜头",
            status=ShotStatus.ready,
            script_excerpt="",
            consistency_score=consistency_score,
        )
    )
    if with_product:
        db.add(Product(id="prod-1", name="测试商品"))
        db.add(
            ProjectProductLink(
                project_id="proj-1",
                chapter_id=None,
                shot_id=None,
                product_id="prod-1",
            )
        )
    if with_reference:
        db.add(
            FileItem(
                id="ref-file-1",
                type=FileType.image,
                name="ref.jpg",
                storage_key="images/ref.jpg",
            )
        )
        db.add(
            ProductImage(
                product_id="prod-1",
                file_id="ref-file-1",
                quality_level=AssetQualityLevel.high,
                view_angle=AssetViewAngle.front,
                is_primary=True,
            )
        )
        db.add(
            FileItem(
                id="ref-file-2",
                type=FileType.image,
                name="ref-tq.jpg",
                storage_key="images/ref-tq.jpg",
            )
        )
        db.add(
            ProductImage(
                product_id="prod-1",
                file_id="ref-file-2",
                quality_level=AssetQualityLevel.medium,
                view_angle=AssetViewAngle.three_quarter,
                is_primary=False,
            )
        )
    await db.flush()


@pytest.fixture
def client_with_db(session_local) -> Generator[TestClient, None, None]:
    """绑定测试 DB 的 TestClient。"""

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


def _seed_sync(session_local, **kwargs: Any) -> None:
    """同步入口：在 fixture 里直接跑 _seed_shot。"""

    async def _run() -> None:
        async with session_local() as db:
            await _seed_shot(db, **kwargs)
            await db.commit()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------


def test_consistency_evidence_returns_score_and_status(
    client_with_db, session_local
) -> None:
    """高分场景：score=0.92 → status=green，URL 字段非空。"""

    _seed_sync(session_local, consistency_score=0.92)

    resp = client_with_db.get(
        "/api/v1/commerce/shots/shot-1/consistency-evidence"
    )
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["code"] == 200
    assert body["message"] == "success"
    data = body["data"]
    assert data["shot_id"] == "shot-1"
    assert data["score"] == pytest.approx(0.92)
    assert data["status"] == "green"
    assert data["reference_image_url"], "reference image URL should be non-empty"
    assert isinstance(data["sampled_frame_urls"], list)
    assert len(data["sampled_frame_urls"]) >= 1
    assert data["reference_view_angle"] == AssetViewAngle.front.value


def test_returns_404_for_unknown_shot(client_with_db) -> None:
    """未知 shot_id → 404，envelope.message 携带 'Shot not found'。

    项目使用统一 ``ApiResponse`` envelope（含全局 HTTPException handler），
    错误会被重写成 ``{code, data:None, message, meta}``，detail 字段不直
    接出现在响应体；本断言覆盖 envelope 形态。
    """

    resp = client_with_db.get(
        "/api/v1/commerce/shots/nonexistent-shot/consistency-evidence"
    )
    assert resp.status_code == 404, resp.text
    body = resp.json()
    assert body["code"] == 404
    assert body["data"] is None
    assert "Shot not found" in str(body.get("message", ""))


def test_includes_retry_count(client_with_db, session_local) -> None:
    """retry_count 字段存在；当前 model 未落地该字段，期望为 None。

    T27-2 引入 ``Shot.retry_count`` 后，service ``getattr`` 会自动透传，
    本用例同样有效（届时只需断言 None 或具体整数）。
    """

    _seed_sync(session_local, consistency_score=0.5)

    resp = client_with_db.get(
        "/api/v1/commerce/shots/shot-1/consistency-evidence"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    data = body["data"]
    assert "retry_count" in data
    assert data["retry_count"] is None or isinstance(data["retry_count"], int)


def test_status_unknown_when_score_is_null(client_with_db, session_local) -> None:
    """score=None → status=unknown；与 score=0.0（合法 cosine）区分。"""

    _seed_sync(session_local, consistency_score=None, with_reference=False)

    resp = client_with_db.get(
        "/api/v1/commerce/shots/shot-1/consistency-evidence"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    data = body["data"]
    assert data["score"] is None
    assert data["status"] == "unknown"


def test_status_amber_in_range_75_to_85(client_with_db, session_local) -> None:
    """边界值：score=0.78 → amber；保证前后端阈值同源。"""

    _seed_sync(session_local, consistency_score=0.78)

    resp = client_with_db.get(
        "/api/v1/commerce/shots/shot-1/consistency-evidence"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    data = body["data"]
    assert data["status"] == "amber"


def test_status_red_below_75(client_with_db, session_local) -> None:
    """低分场景：score=0.6 → red。"""

    _seed_sync(session_local, consistency_score=0.6)

    resp = client_with_db.get(
        "/api/v1/commerce/shots/shot-1/consistency-evidence"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    data = body["data"]
    assert data["status"] == "red"
