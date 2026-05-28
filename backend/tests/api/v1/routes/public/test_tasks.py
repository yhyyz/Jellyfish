"""``GET /api/v1/public/commerce/tasks/{task_id}`` 测试（P4 W24-T3）。

覆盖 5 类用例：

1. ``test_public_tasks_returns_status_for_owner``：用 owner 自己的
   ``X-API-Key`` 查询，命中后返回 ``PublicTaskStatusRead`` 简化 envelope；
2. ``test_public_tasks_returns_404_for_other_key``：用另一把合法 key 查
   询同一任务，必须返回 ``404``（**不是 403**），防嗅探；
3. ``test_public_tasks_returns_404_for_unknown_id``：未知 task_id 返回
   ``404``，不泄露任务表中是否存在；
4. ``test_public_tasks_requires_x_api_key_header``：缺 ``X-API-Key`` 头
   或带错误 key，必须由 :class:`ApiKeyMiddleware` 在路由前拦截为
   ``401``；
5. ``test_public_tasks_response_envelope_fields``：响应壳的 ``data``
   必须只含 ``status`` / ``progress`` / ``result_file_id`` / ``error``
   四个字段，**不**泄露 ``payload`` / ``executor_*`` / ``cancel_reason``
   等内部字段，对外契约保持最小表面。
"""

# pylint: disable=invalid-name

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import AsyncGenerator

import bcrypt
import pytest
from fastapi.testclient import TestClient
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
from app.models.task import GenerationDeliveryMode, GenerationTask, GenerationTaskStatus


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


async def _make_engine() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
    """构建一次性内存 SQLite 引擎并建表。

    使用 ``cache=shared`` URI 让 middleware 与 route handler 在不同会话
    里看到同一份数据；纯 ``:memory:`` 的连接级私有库会让中间件读不到
    刚刚 seed 的 ``ApiKeyQuota`` 行。
    """

    engine = create_async_engine(
        "sqlite+aiosqlite:///file:test_public_tasks?mode=memory&cache=shared&uri=true",
        future=True,
    )
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
) -> str:
    """落一行 ``ApiKeyQuota`` 并回传 bcrypt hash。"""

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
                consumed_today=0,
                consumed_this_month=0,
                last_reset_daily=today,
                last_reset_monthly=today,
                is_active=is_active,
            )
        )
        await session.commit()
    return api_key_hash


async def _seed_task(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    task_id: str,
    owner_hash: str | None,
    status: GenerationTaskStatus = GenerationTaskStatus.running,
    progress: int = 42,
    result: dict | None = None,
    error: str = "",
) -> None:
    """落一条 ``GenerationTask``，按 :class:`TaskManager` 的 payload 结构写归属。

    ``payload = {"task_class", "task_kind", "run_args": {"api_key_hash": ...}}``
    与 :func:`app.core.task_manager.manager.TaskManager.create` 的契约保
    持一致；归属为 ``None`` 时模拟"非公开通道创建的任务"，对所有调用方
    都应不可见。
    """

    payload: dict = {
        "task_class": "ProductExtractTask",
        "task_kind": "product_info_extract",
        "run_args": {} if owner_hash is None else {"api_key_hash": owner_hash},
    }
    async with sessionmaker() as session:
        session.add(
            GenerationTask(
                id=task_id,
                mode=GenerationDeliveryMode.async_polling,
                task_kind="product_info_extract",
                status=status,
                progress=progress,
                payload=payload,
                result=result,
                error=error,
            )
        )
        await session.commit()


def _wire_app(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    """把 in-memory sessionmaker 同时挂到 ``app.state`` 和 ``get_db`` 覆盖上。

    - ``app.state.session_maker`` 让
      :func:`app.core.api_key_auth.enforce_public_request` 中间件读到
      同一份测试数据；
    - ``app.dependency_overrides[get_db]`` 让路由 handler 也共用同一
      会话（提交独立但数据可见，因为 SQLite 共享 cache URI）。
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

    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1) Owner can read its own task
# ---------------------------------------------------------------------------


def test_public_tasks_returns_status_for_owner() -> None:
    """归属一致 → 200 + envelope 字段正确。"""

    async def _setup() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine, str]:
        sessionmaker, engine = await _make_engine()
        owner_hash = await _seed_api_key(
            sessionmaker, plaintext="public-owner-key-1"
        )
        await _seed_task(
            sessionmaker,
            task_id="task-owner-1",
            owner_hash=owner_hash,
            status=GenerationTaskStatus.succeeded,
            progress=100,
            result={"file_id": "file-xyz-001"},
            error="",
        )
        return sessionmaker, engine, owner_hash

    sessionmaker, engine, _ = _run(_setup())
    _wire_app(sessionmaker)
    try:
        client = TestClient(app)
        response = client.get(
            "/api/v1/public/commerce/tasks/task-owner-1",
            headers={"X-API-Key": "public-owner-key-1"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["code"] == 200
        data = body["data"]
        assert data == {
            "status": "succeeded",
            "progress": 100,
            "result_file_id": "file-xyz-001",
            "error": "",
        }
    finally:
        _unwire_app()
        _run(engine.dispose())


# ---------------------------------------------------------------------------
# 2) Cross-tenant access returns 404 (not 403, anti-sniff)
# ---------------------------------------------------------------------------


def test_public_tasks_returns_404_for_other_key() -> None:
    """另一把合法 key 访问他人的任务必须 404，而非 403。"""

    async def _setup() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
        sessionmaker, engine = await _make_engine()
        owner_hash = await _seed_api_key(
            sessionmaker, plaintext="public-owner-key-2", description="owner"
        )
        # 第二把合法 key（active 且 quota 充足）
        await _seed_api_key(
            sessionmaker, plaintext="public-attacker-key-2", description="attacker"
        )
        await _seed_task(
            sessionmaker,
            task_id="task-owned-by-someone-else",
            owner_hash=owner_hash,
            status=GenerationTaskStatus.running,
            progress=10,
        )
        return sessionmaker, engine

    sessionmaker, engine = _run(_setup())
    _wire_app(sessionmaker)
    try:
        client = TestClient(app)
        response = client.get(
            "/api/v1/public/commerce/tasks/task-owned-by-someone-else",
            headers={"X-API-Key": "public-attacker-key-2"},
        )
        assert response.status_code == 404, response.text
        body = response.json()
        # 与"任务真不存在"映射到同一错误信号，不暴露归属差异
        assert body["code"] == 404
    finally:
        _unwire_app()
        _run(engine.dispose())


# ---------------------------------------------------------------------------
# 3) Unknown task id → 404
# ---------------------------------------------------------------------------


def test_public_tasks_returns_404_for_unknown_id() -> None:
    """完全不存在的 task_id 也必须返回 404。"""

    async def _setup() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
        sessionmaker, engine = await _make_engine()
        await _seed_api_key(sessionmaker, plaintext="public-key-3")
        return sessionmaker, engine

    sessionmaker, engine = _run(_setup())
    _wire_app(sessionmaker)
    try:
        client = TestClient(app)
        response = client.get(
            "/api/v1/public/commerce/tasks/no-such-task-id",
            headers={"X-API-Key": "public-key-3"},
        )
        assert response.status_code == 404, response.text
    finally:
        _unwire_app()
        _run(engine.dispose())


# ---------------------------------------------------------------------------
# 4) Missing X-API-Key header → 401 (caught by middleware)
# ---------------------------------------------------------------------------


def test_public_tasks_requires_x_api_key_header() -> None:
    """缺头 / 错头都必须由中间件拦截为 401，路由不参与。"""

    async def _setup() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine, str]:
        sessionmaker, engine = await _make_engine()
        owner_hash = await _seed_api_key(sessionmaker, plaintext="public-key-4")
        await _seed_task(
            sessionmaker,
            task_id="task-401-probe",
            owner_hash=owner_hash,
        )
        return sessionmaker, engine, owner_hash

    sessionmaker, engine, _ = _run(_setup())
    _wire_app(sessionmaker)
    try:
        client = TestClient(app)
        # 缺头
        missing = client.get("/api/v1/public/commerce/tasks/task-401-probe")
        assert missing.status_code == 401, missing.text
        # 错头
        wrong = client.get(
            "/api/v1/public/commerce/tasks/task-401-probe",
            headers={"X-API-Key": "wrong-plaintext"},
        )
        assert wrong.status_code == 401, wrong.text
    finally:
        _unwire_app()
        _run(engine.dispose())


# ---------------------------------------------------------------------------
# 5) Envelope keeps minimal surface (no payload / executor leakage)
# ---------------------------------------------------------------------------


def test_public_tasks_response_envelope_fields() -> None:
    """``data`` 仅暴露 4 个字段，不泄露 ``payload`` / ``executor_*`` 等内部字段。"""

    async def _setup() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
        sessionmaker, engine = await _make_engine()
        owner_hash = await _seed_api_key(
            sessionmaker, plaintext="public-key-5"
        )
        await _seed_task(
            sessionmaker,
            task_id="task-envelope-5",
            owner_hash=owner_hash,
            status=GenerationTaskStatus.failed,
            progress=70,
            result=None,
            error="供应商超时",
        )
        return sessionmaker, engine

    sessionmaker, engine = _run(_setup())
    _wire_app(sessionmaker)
    try:
        client = TestClient(app)
        response = client.get(
            "/api/v1/public/commerce/tasks/task-envelope-5",
            headers={"X-API-Key": "public-key-5"},
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert set(data.keys()) == {
            "status",
            "progress",
            "result_file_id",
            "error",
        }
        # 无 single-file result，result_file_id 必须为 None
        assert data["result_file_id"] is None
        assert data["status"] == "failed"
        assert data["error"] == "供应商超时"
    finally:
        _unwire_app()
        _run(engine.dispose())
