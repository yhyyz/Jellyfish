"""``POST /api/v1/public/commerce/generate`` 测试（P4 W24-T2）。

覆盖 6 类用例：

1. ``test_generate_returns_202_with_task_id``：合法 X-API-Key + 已存在
   product/formula → 返回 202 + ``PublicGenerateResponse``；
2. ``test_generate_404_for_unknown_product``：未知 ``product_id`` → 404；
3. ``test_generate_404_for_unknown_formula``：未知 ``formula_id`` → 404；
4. ``test_generate_consumes_quota_on_success``：成功后 ``consumed_today``
   必须自增 1（验证中间件配额扣减真实生效）；
5. ``test_generate_429_when_quota_exhausted``：seed 配额已触顶，应被中
   间件拦截为 429（``Retry-After`` 头存在），路由不应被执行；
6. ``test_generate_writes_api_key_hash_to_run_args``：
   ``GenerationTask.payload['run_args']['api_key_hash']`` 必须等于调用方
   的 bcrypt hash —— **关键**，T24-3 跨租户隔离的前置依赖。
"""

# pylint: disable=invalid-name

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import AsyncGenerator

import bcrypt
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.models  # noqa: F401  pylint: disable=unused-import  ensure all models registered

from app.core.api_key_auth import BCRYPT_COST
from app.core.db import Base
from app.dependencies import get_db
from app.main import app
from app.models.api_quota import ApiKeyQuota
from app.models.commerce_assets import Product
from app.models.story_formula import StoryFormula
from app.models.studio_prompts_files_timeline import PromptTemplate
from app.models.task import GenerationTask
from app.models.types import PromptCategory


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


# 每个测试用例独立的 in-memory SQLite cache key —— 与 test_tasks.py 的
# ``test_public_tasks`` 错开，避免 sibling 测试在同一进程里共享同一份内
# 存数据库导致脏数据干扰。
_DB_URI = "sqlite+aiosqlite:///file:test_public_generate?mode=memory&cache=shared&uri=true"


async def _make_engine() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
    """构建一次性内存 SQLite 引擎并建表。

    用 ``cache=shared`` URI 让 middleware 与 route handler 在不同会话里看到
    同一份数据；纯 ``:memory:`` 的连接级私有库会让中间件读不到刚刚 seed
    的 :class:`ApiKeyQuota` 行（与 :file:`test_tasks.py` 的同名 helper 行
    为对齐）。
    """

    engine = create_async_engine(_DB_URI, future=True)
    sessionmaker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    return sessionmaker, engine


async def _seed_api_key(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    plaintext: str,
    description: str = "test",
    is_active: bool = True,
    daily_limit: int = 1000,
    consumed_today: int = 0,
) -> str:
    """落一行 ``ApiKeyQuota`` 并回传 bcrypt hash。

    ``daily_limit`` / ``consumed_today`` 默认值留给主流程用例；耗尽配额
    用例显式把 ``consumed_today=daily_limit`` 触发 429。
    """

    today = datetime.now(UTC).date()
    api_key_hash = bcrypt.hashpw(
        plaintext.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_COST)
    ).decode("utf-8")
    async with sessionmaker() as session:
        session.add(
            ApiKeyQuota(
                api_key_hash=api_key_hash,
                description=description,
                daily_limit=daily_limit,
                monthly_limit=daily_limit * 30,
                rate_per_minute=600,
                consumed_today=consumed_today,
                consumed_this_month=consumed_today,
                last_reset_daily=today,
                last_reset_monthly=today,
                is_active=is_active,
            )
        )
        await session.commit()
    return api_key_hash


async def _seed_product_and_formula(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    product_id: str = "prod-public-1",
    formula_id: str = "formula-public-1",
    template_id: str = "tpl-public-1",
) -> None:
    """落 ``Product`` + ``StoryFormula`` + 必需的 ``PromptTemplate``。

    StoryFormula.prompt_template_id 是 NOT NULL + ON DELETE RESTRICT
    外键，因此必须先 seed 一条 :class:`PromptTemplate` 才能创建公式。
    """

    async with sessionmaker() as session:
        session.add(
            PromptTemplate(
                id=template_id,
                category=PromptCategory.story_formula_generator,
                name="占位模板",
                preview="",
                content="占位",
                variables=[],
                is_default=True,
                is_system=True,
            )
        )
        await session.flush()
        session.add(
            Product(
                id=product_id,
                name=f"测试商品-{product_id}",
            )
        )
        session.add(
            StoryFormula(
                id=formula_id,
                name="占位公式",
                structure={"beats": []},
                risk_flags=[],
                sample_dialog="占位剧本",
                typical_duration_sec=60,
                typical_shot_count=4,
                psychology="占位",
                use_cases=[],
                avoid_cases=[],
                prompt_template_id=template_id,
                is_system=True,
                sort_order=0,
            )
        )
        await session.commit()


def _wire_app(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    """把 in-memory sessionmaker 同时挂到 ``app.state`` 和 ``get_db`` 覆盖上。

    - ``app.state.session_maker`` 让 :func:`enforce_public_request` 中间件
      读到同一份测试数据；
    - ``app.dependency_overrides[get_db]`` 让路由 handler 共用同一会话。
    """

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:  # noqa: BLE001
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    app.state.session_maker = sessionmaker


def _unwire_app() -> None:
    app.dependency_overrides.pop(get_db, None)
    if hasattr(app.state, "session_maker"):
        delattr(app.state, "session_maker")


def _run(coro):
    """同步桥接，避免在 sync 测试函数里强引入 pytest-asyncio。"""

    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1) Happy path: 202 + envelope + status="queued"
# ---------------------------------------------------------------------------


def test_generate_returns_202_with_task_id() -> None:
    """合法 X-API-Key + 已存在 product/formula → 202 + 完整 envelope。"""

    async def _setup() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
        sessionmaker, engine = await _make_engine()
        await _seed_api_key(sessionmaker, plaintext="public-gen-key-1")
        await _seed_product_and_formula(sessionmaker)
        return sessionmaker, engine

    sessionmaker, engine = _run(_setup())
    _wire_app(sessionmaker)
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/public/commerce/generate",
            headers={"X-API-Key": "public-gen-key-1"},
            json={
                "product_id": "prod-public-1",
                "formula_id": "formula-public-1",
                "variant_count": 2,
            },
        )
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["code"] == 202
        data = body["data"]
        assert set(data.keys()) == {"task_id", "status", "estimated_eta_sec"}
        assert isinstance(data["task_id"], str) and data["task_id"]
        assert data["status"] == "queued"
        # 2 variants × 60s/variant = 120s
        assert data["estimated_eta_sec"] == 120
    finally:
        _unwire_app()
        _run(engine.dispose())


# ---------------------------------------------------------------------------
# 2) Unknown product → 404
# ---------------------------------------------------------------------------


def test_generate_404_for_unknown_product() -> None:
    """未注册 ``product_id`` → 404，不入队任何任务。"""

    async def _setup() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
        sessionmaker, engine = await _make_engine()
        await _seed_api_key(sessionmaker, plaintext="public-gen-key-2")
        # 只 seed formula，不 seed product
        async with sessionmaker() as session:
            session.add(
                PromptTemplate(
                    id="tpl-2",
                    category=PromptCategory.story_formula_generator,
                    name="占位",
                    preview="",
                    content="占位",
                    variables=[],
                    is_default=True,
                    is_system=True,
                )
            )
            await session.flush()
            session.add(
                StoryFormula(
                    id="formula-2",
                    name="占位",
                    structure={"beats": []},
                    risk_flags=[],
                    sample_dialog="占位",
                    typical_duration_sec=60,
                    typical_shot_count=4,
                    psychology="占位",
                    use_cases=[],
                    avoid_cases=[],
                    prompt_template_id="tpl-2",
                    is_system=True,
                    sort_order=0,
                )
            )
            await session.commit()
        return sessionmaker, engine

    sessionmaker, engine = _run(_setup())
    _wire_app(sessionmaker)
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/public/commerce/generate",
            headers={"X-API-Key": "public-gen-key-2"},
            json={
                "product_id": "nonexistent-product",
                "formula_id": "formula-2",
            },
        )
        assert response.status_code == 404, response.text
        body = response.json()
        assert body["code"] == 404
        assert "Product" in body["message"]

        # 任务不应入队
        async def _count_tasks() -> int:
            async with sessionmaker() as session:
                rows = (await session.execute(select(GenerationTask))).scalars().all()
                return len(rows)

        assert _run(_count_tasks()) == 0
    finally:
        _unwire_app()
        _run(engine.dispose())


# ---------------------------------------------------------------------------
# 3) Unknown formula → 404
# ---------------------------------------------------------------------------


def test_generate_404_for_unknown_formula() -> None:
    """未注册 ``formula_id`` → 404，product 存在也不应入队。"""

    async def _setup() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
        sessionmaker, engine = await _make_engine()
        await _seed_api_key(sessionmaker, plaintext="public-gen-key-3")
        async with sessionmaker() as session:
            session.add(Product(id="prod-3", name="测试商品-3"))
            await session.commit()
        return sessionmaker, engine

    sessionmaker, engine = _run(_setup())
    _wire_app(sessionmaker)
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/public/commerce/generate",
            headers={"X-API-Key": "public-gen-key-3"},
            json={
                "product_id": "prod-3",
                "formula_id": "nonexistent-formula",
            },
        )
        assert response.status_code == 404, response.text
        body = response.json()
        assert body["code"] == 404
        assert "StoryFormula" in body["message"]
    finally:
        _unwire_app()
        _run(engine.dispose())


# ---------------------------------------------------------------------------
# 4) Quota consumed_today must increment after success
# ---------------------------------------------------------------------------


def test_generate_consumes_quota_on_success() -> None:
    """成功后中间件应把 ``consumed_today`` 自增 1。"""

    async def _setup() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine, str]:
        sessionmaker, engine = await _make_engine()
        api_key_hash = await _seed_api_key(
            sessionmaker, plaintext="public-gen-key-4", daily_limit=10
        )
        await _seed_product_and_formula(
            sessionmaker,
            product_id="prod-4",
            formula_id="formula-4",
            template_id="tpl-4",
        )
        return sessionmaker, engine, api_key_hash

    sessionmaker, engine, api_key_hash = _run(_setup())
    _wire_app(sessionmaker)
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/public/commerce/generate",
            headers={"X-API-Key": "public-gen-key-4"},
            json={
                "product_id": "prod-4",
                "formula_id": "formula-4",
            },
        )
        assert response.status_code == 202, response.text

        async def _read_quota() -> int:
            async with sessionmaker() as session:
                row = await session.get(ApiKeyQuota, api_key_hash)
                assert row is not None
                return row.consumed_today

        assert _run(_read_quota()) == 1
    finally:
        _unwire_app()
        _run(engine.dispose())


# ---------------------------------------------------------------------------
# 5) Quota exhausted → 429 (caught by middleware, route never runs)
# ---------------------------------------------------------------------------


def test_generate_429_when_quota_exhausted() -> None:
    """seed 配额已触顶，中间件应直接拦截为 429 + Retry-After。"""

    async def _setup() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
        sessionmaker, engine = await _make_engine()
        # consumed_today == daily_limit → consume_quota 会 rowcount=0 失败
        await _seed_api_key(
            sessionmaker,
            plaintext="public-gen-key-5",
            daily_limit=5,
            consumed_today=5,
        )
        await _seed_product_and_formula(
            sessionmaker,
            product_id="prod-5",
            formula_id="formula-5",
            template_id="tpl-5",
        )
        return sessionmaker, engine

    sessionmaker, engine = _run(_setup())
    _wire_app(sessionmaker)
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/public/commerce/generate",
            headers={"X-API-Key": "public-gen-key-5"},
            json={
                "product_id": "prod-5",
                "formula_id": "formula-5",
            },
        )
        assert response.status_code == 429, response.text
        # Retry-After 头是 quota exhausted 的契约一部分（参见
        # QUOTA_EXHAUSTED_RETRY_AFTER_SECONDS = 24h）
        assert response.headers.get("Retry-After") is not None

        # 任务必须未入队（route 根本未执行）
        async def _count_tasks() -> int:
            async with sessionmaker() as session:
                rows = (await session.execute(select(GenerationTask))).scalars().all()
                return len(rows)

        assert _run(_count_tasks()) == 0
    finally:
        _unwire_app()
        _run(engine.dispose())


# ---------------------------------------------------------------------------
# 6) api_key_hash must land in run_args (T24-3 isolation prerequisite)
# ---------------------------------------------------------------------------


def test_generate_writes_api_key_hash_to_run_args() -> None:
    """``GenerationTask.payload['run_args']['api_key_hash']`` 必须等于调用方 hash。

    这是 T24-3 ``GET /commerce/tasks/{id}`` 跨租户隔离的前置依赖：T24-3
    从 ``payload['run_args']['api_key_hash']`` 读出归属并与
    ``request.state.api_key_quota.api_key_hash`` 比对，缺这一字段的任务
    会被对所有调用方判为"不可见"。
    """

    async def _setup() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine, str]:
        sessionmaker, engine = await _make_engine()
        api_key_hash = await _seed_api_key(
            sessionmaker, plaintext="public-gen-key-6"
        )
        await _seed_product_and_formula(
            sessionmaker,
            product_id="prod-6",
            formula_id="formula-6",
            template_id="tpl-6",
        )
        return sessionmaker, engine, api_key_hash

    sessionmaker, engine, expected_hash = _run(_setup())
    _wire_app(sessionmaker)
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/public/commerce/generate",
            headers={"X-API-Key": "public-gen-key-6"},
            json={
                "product_id": "prod-6",
                "formula_id": "formula-6",
                "archetype": "underdog",
                "variant_count": 3,
            },
        )
        assert response.status_code == 202, response.text
        task_id = response.json()["data"]["task_id"]

        async def _load_task() -> GenerationTask:
            async with sessionmaker() as session:
                task = await session.get(GenerationTask, task_id)
                assert task is not None
                return task

        task = _run(_load_task())
        run_args = task.payload["run_args"]
        # 关键断言：归属字段对齐
        assert run_args["api_key_hash"] == expected_hash
        # 同时校验业务字段被透传
        assert run_args["product_id"] == "prod-6"
        assert run_args["formula_id"] == "formula-6"
        assert run_args["archetype"] == "underdog"
        assert run_args["variant_count"] == 3
        # task_kind 走占位（W24-T2 范围内，完整 commerce_generate 不在 P4）
        assert task.task_kind == "story_video_batch_generate"
    finally:
        _unwire_app()
        _run(engine.dispose())
