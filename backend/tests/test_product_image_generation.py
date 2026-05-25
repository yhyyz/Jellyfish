"""W14-T2: ``ProductImageGenerationService`` + 入队路由的端到端测试。

测试策略
--------

- 文件型 SQLite + ``Base.metadata.create_all``：确保 ``products`` /
  ``product_images`` / ``prompt_templates`` / ``generation_tasks`` 等表
  按真实 ORM 路径建好；
- ``app.dependency_overrides[get_db]`` 把路由层绑到测试 session；
- ``patch("app.services.commerce.product_image_generation.celery_app.send_task")``
  避免真实投递；同时断言入队参数（``task.execute`` / args / queue=fast）；
- 模板：测试 setup 时手工 insert 两条 ``is_system=True`` 的内置模板
  （``product_image_front_v1`` / ``product_image_other_v1``），与 W3-T1
  bootstrap 后的形态一致；自定义模板单独再 insert 一条覆盖测试用。

覆盖点（10 项）
---------------

1. service: 商品不存在 → 404；
2. service: ``view_angle=FRONT`` → ``product_image_front_v1`` 命中；
3. service: 非 front → ``product_image_other_v1`` 命中；
4. service: ``Product.prompt_template_id`` 非空 → 自定义模板优先；
5. service: 渲染上下文包含 selling_points / brand / name / style；
6. service: ``run_args`` 形态正确 + ``celery_app.send_task`` 被调用一次；
7. API: ``POST /products/{id}/images/generate`` 返回 202 + envelope；
8. API: 未知 product_id → 404；
9. API: 请求体 extra 字段 → 422；
10. API: 响应包含 ``task_id`` / ``template_used`` / ``view_angle``。
"""

# pylint: disable=redefined-outer-name,too-many-arguments,too-many-locals

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncGenerator, Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.dependencies import get_db
from app.main import app
from app.models.commerce_assets import Product
from app.models.studio_prompts_files_timeline import PromptTemplate
from app.models.task import GenerationTask, GenerationTaskStatus
from app.models.types import (
    AssetViewAngle,
    ProductCategory,
    ProjectStyle,
    ProjectVisualStyle,
    PromptCategory,
)
from app.services.commerce.product_image_generation import (
    DEFAULT_FRONT_TEMPLATE_ID,
    DEFAULT_OTHER_TEMPLATE_ID,
    TASK_KIND_IMAGE_GENERATION,
    ProductImageGenerationService,
)


_UUID_HEX = re.compile(r"^[0-9a-f]{32}$")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def session_local(tmp_path) -> Generator[async_sessionmaker[AsyncSession], None, None]:
    """每个测试一份独立 SQLite 文件 + 全表创建。"""

    db_path = tmp_path / "product-image-generation.db"
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


@pytest.fixture
def seeded_session(session_local) -> async_sessionmaker[AsyncSession]:
    """预置内置 prompt templates，模拟 W3-T1 bootstrap 完成后的状态。"""

    async def _seed() -> None:
        async with session_local() as db:
            db.add(
                PromptTemplate(
                    id=DEFAULT_FRONT_TEMPLATE_ID,
                    category=PromptCategory.product_image_front,
                    name="商品正面参考图（系统默认）",
                    preview="正面参考图 prompt",
                    content=(
                        "为商品生成正面参考图。\n"
                        "商品名：{{ product.name }}\n"
                        "品牌：{{ product.brand }}\n"
                        "卖点：{{ product.selling_points }}\n"
                        "风格：{{ style }}\n"
                    ),
                    variables=["product", "style"],
                    is_default=True,
                    is_system=True,
                )
            )
            db.add(
                PromptTemplate(
                    id=DEFAULT_OTHER_TEMPLATE_ID,
                    category=PromptCategory.product_image_other,
                    name="商品多视角参考图（系统默认）",
                    preview="多视角 prompt",
                    content=(
                        "为商品生成 {{ view_angle }} 角度参考图。\n"
                        "商品名：{{ product.name }}\n"
                    ),
                    variables=["product", "view_angle"],
                    is_default=True,
                    is_system=True,
                )
            )
            await db.commit()

    asyncio.run(_seed())
    return session_local


@pytest.fixture
def client_with_db(seeded_session) -> Generator[TestClient, None, None]:
    """绑定测试库的 FastAPI TestClient。"""

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with seeded_session() as session:
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


@pytest.fixture
def mock_send_task() -> Generator[MagicMock, None, None]:
    """patch celery 投递入口；测试断言其参数。"""

    target = "app.services.commerce.product_image_generation.celery_app.send_task"
    with patch(target) as mocked:
        mocked.return_value = MagicMock(id="celery-mock-id")
        yield mocked


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_product(
    *,
    product_id: str = "p-123",
    name: str = "兰蔻小黑瓶精华 50ml",
    brand: str = "Lancôme",
    style: ProjectStyle = ProjectStyle.real_people_city,
    selling_points: list[str] | None = None,
    prompt_template_id: str | None = None,
) -> Product:
    return Product(
        id=product_id,
        name=name,
        brand=brand,
        category=ProductCategory.beauty,
        description="测试商品",
        selling_points=list(selling_points or ["卖点 1", "卖点 2"]),
        pain_points_solved=[],
        target_audience={"age_range": "25-34"},
        catchphrases=[],
        competitor_names=[],
        health_disclaimer_required=False,
        visual_style=ProjectVisualStyle.live_action,
        style=style,
        prompt_template_id=prompt_template_id,
    )


async def _seed_product(session_local, product: Product) -> None:
    async with session_local() as db:
        db.add(product)
        await db.commit()


async def _fetch_task(session_local, task_id: str) -> GenerationTask | None:
    async with session_local() as db:
        return await db.get(GenerationTask, task_id)


# ---------------------------------------------------------------------------
# Service-level tests (1–6)
# ---------------------------------------------------------------------------


def test_service_raises_404_when_product_missing(seeded_session, mock_send_task) -> None:
    """商品不存在 → 抛 404，未投递 Celery。"""

    async def _run() -> None:
        async with seeded_session() as db:
            service = ProductImageGenerationService(db)
            with pytest.raises(Exception) as exc_info:
                await service.enqueue_product_image_generation(
                    product_id="does-not-exist",
                    view_angle=AssetViewAngle.front.value,
                )
            # FastAPI HTTPException 不是基类 Exception 子类型暴露，但有
            # status_code 属性；这里通过 detail 与 status_code 验证。
            assert getattr(exc_info.value, "status_code", None) == 404

    asyncio.run(_run())
    mock_send_task.assert_not_called()


def test_service_picks_front_template_for_view_angle_front(
    seeded_session, mock_send_task
) -> None:
    """``view_angle=FRONT`` 命中 ``product_image_front_v1``。"""

    asyncio.run(_seed_product(seeded_session, _make_product()))

    async def _run() -> dict[str, Any]:
        async with seeded_session() as db:
            service = ProductImageGenerationService(db)
            return await service.enqueue_product_image_generation(
                product_id="p-123",
                view_angle=AssetViewAngle.front.value,
            )

    payload = asyncio.run(_run())
    assert payload["template_used"] == DEFAULT_FRONT_TEMPLATE_ID
    assert payload["view_angle"] == AssetViewAngle.front.value
    mock_send_task.assert_called_once()


def test_service_picks_other_template_for_non_front_view_angle(
    seeded_session, mock_send_task
) -> None:
    """非 ``FRONT`` 视角命中 ``product_image_other_v1``。"""

    asyncio.run(_seed_product(seeded_session, _make_product()))

    async def _run() -> dict[str, Any]:
        async with seeded_session() as db:
            service = ProductImageGenerationService(db)
            return await service.enqueue_product_image_generation(
                product_id="p-123",
                view_angle=AssetViewAngle.detail.value,
            )

    payload = asyncio.run(_run())
    assert payload["template_used"] == DEFAULT_OTHER_TEMPLATE_ID
    assert payload["view_angle"] == AssetViewAngle.detail.value
    mock_send_task.assert_called_once()


def test_service_respects_custom_product_prompt_template_id(
    seeded_session, mock_send_task
) -> None:
    """``Product.prompt_template_id`` 非空时优先使用自定义模板。"""

    custom_id = "custom-front-tpl"

    async def _seed_custom() -> None:
        async with seeded_session() as db:
            db.add(
                PromptTemplate(
                    id=custom_id,
                    category=PromptCategory.product_image_front,
                    name="自定义正面图模板",
                    preview="custom",
                    content="自定义模板：{{ product.name }} / {{ style }}",
                    variables=["product", "style"],
                    is_default=False,
                    is_system=False,
                )
            )
            db.add(_make_product(prompt_template_id=custom_id))
            await db.commit()

    asyncio.run(_seed_custom())

    async def _run() -> dict[str, Any]:
        async with seeded_session() as db:
            service = ProductImageGenerationService(db)
            # 自定义模板不应被 view_angle=detail 改写
            return await service.enqueue_product_image_generation(
                product_id="p-123",
                view_angle=AssetViewAngle.detail.value,
            )

    payload = asyncio.run(_run())
    assert payload["template_used"] == custom_id
    mock_send_task.assert_called_once()


def test_service_renders_template_with_product_fields(
    seeded_session, mock_send_task, session_local
) -> None:
    """渲染上下文包含 selling_points / brand / name / style。"""

    asyncio.run(
        _seed_product(
            seeded_session,
            _make_product(
                name="兰蔻小黑瓶精华",
                brand="Lancôme",
                selling_points=["72H 锁水", "提亮肤色"],
                style=ProjectStyle.real_people_city,
            ),
        )
    )

    async def _run() -> dict[str, Any]:
        async with seeded_session() as db:
            service = ProductImageGenerationService(db)
            payload = await service.enqueue_product_image_generation(
                product_id="p-123",
                view_angle=AssetViewAngle.front.value,
            )
            await db.commit()
            return payload

    payload = asyncio.run(_run())
    task_row = asyncio.run(_fetch_task(session_local, payload["task_id"]))
    assert task_row is not None
    rendered_prompt = task_row.payload["run_args"]["input"]["prompt"]
    assert "兰蔻小黑瓶精华" in rendered_prompt
    assert "Lancôme" in rendered_prompt
    assert "72H 锁水" in rendered_prompt
    assert ProjectStyle.real_people_city.value in rendered_prompt
    mock_send_task.assert_called_once()


def test_service_enqueues_image_generation_task_with_correct_payload(
    seeded_session, mock_send_task, session_local
) -> None:
    """``run_args`` 形态正确，且 ``celery_app.send_task`` 被以 fast 队列调用一次。"""

    asyncio.run(_seed_product(seeded_session, _make_product()))

    async def _run() -> dict[str, Any]:
        async with seeded_session() as db:
            service = ProductImageGenerationService(db)
            payload = await service.enqueue_product_image_generation(
                product_id="p-123",
                view_angle=AssetViewAngle.front.value,
                quality_level="HIGH",
                reference_file_id="file-xyz",
            )
            await db.commit()
            return payload

    payload = asyncio.run(_run())
    assert _UUID_HEX.match(payload["task_id"])

    task_row = asyncio.run(_fetch_task(session_local, payload["task_id"]))
    assert task_row is not None
    assert task_row.task_kind == TASK_KIND_IMAGE_GENERATION
    assert task_row.status == GenerationTaskStatus.pending

    run_args = task_row.payload["run_args"]
    assert run_args["relation_type"] == "product_image"
    assert run_args["relation_entity_id"] == "p-123"
    assert run_args["input"]["purpose"] == "product_image"
    assert run_args["input"]["prompt"]
    assert run_args["input"]["images"] == [{"id": "file-xyz", "kind": "reference"}]
    assert run_args["render_context"]["template_id"] == DEFAULT_FRONT_TEMPLATE_ID
    assert run_args["render_context"]["view_angle"] == AssetViewAngle.front.value
    assert run_args["render_context"]["quality_level"] == "HIGH"

    mock_send_task.assert_called_once()
    args, kwargs = mock_send_task.call_args
    assert args[0] == "task.execute"
    assert kwargs["args"] == [payload["task_id"]]
    assert kwargs["queue"] == "fast"


# ---------------------------------------------------------------------------
# API-level tests (7–10)
# ---------------------------------------------------------------------------


def test_api_returns_202_with_envelope(
    client_with_db, mock_send_task, seeded_session
) -> None:
    """POST 路由返回 202 + ApiResponse 标准外壳。"""

    asyncio.run(_seed_product(seeded_session, _make_product()))

    resp = client_with_db.post(
        "/api/v1/studio/products/p-123/images/generate",
        json={"view_angle": AssetViewAngle.front.value, "quality_level": "HIGH"},
    )
    assert resp.status_code == 202, resp.text

    body = resp.json()
    assert body["code"] == 202
    assert body["message"] == "success"
    assert body["data"]["product_id"] == "p-123"
    assert body["data"]["template_used"] == DEFAULT_FRONT_TEMPLATE_ID
    assert _UUID_HEX.match(body["data"]["task_id"])
    mock_send_task.assert_called_once()


def test_api_returns_404_on_unknown_product(client_with_db, mock_send_task) -> None:
    """未知 product_id → 404，且未投递 Celery。"""

    resp = client_with_db.post(
        "/api/v1/studio/products/missing/images/generate",
        json={"view_angle": AssetViewAngle.front.value},
    )
    assert resp.status_code == 404
    mock_send_task.assert_not_called()


def test_api_rejects_extra_fields_in_request_body(
    client_with_db, mock_send_task, seeded_session
) -> None:
    """``extra="forbid"`` → 多余字段返回 422，不投递 Celery。"""

    asyncio.run(_seed_product(seeded_session, _make_product()))

    resp = client_with_db.post(
        "/api/v1/studio/products/p-123/images/generate",
        json={
            "view_angle": AssetViewAngle.front.value,
            "rogue_field": "should_be_rejected",
        },
    )
    assert resp.status_code == 422
    mock_send_task.assert_not_called()


def test_api_response_contains_task_id_and_template_used(
    client_with_db, mock_send_task, seeded_session
) -> None:
    """返回 ``task_id`` / ``template_used`` / ``view_angle`` 三个字段。"""

    asyncio.run(_seed_product(seeded_session, _make_product()))

    resp = client_with_db.post(
        "/api/v1/studio/products/p-123/images/generate",
        json={"view_angle": AssetViewAngle.detail.value},
    )
    assert resp.status_code == 202
    data = resp.json()["data"]
    assert set(data.keys()) >= {"task_id", "product_id", "view_angle", "template_used"}
    assert data["view_angle"] == AssetViewAngle.detail.value
    assert data["template_used"] == DEFAULT_OTHER_TEMPLATE_ID
    mock_send_task.assert_called_once()
