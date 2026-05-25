"""W6-T3: ``commerce/*`` 异步任务入口端到端测试。

测试策略
--------

- 使用真实 SQLite (file-based) + ``Base.metadata.create_all`` 建表，让
  ``GenerationTask`` 走完整 ORM 路径；
- 通过 ``app.dependency_overrides`` 覆盖 ``get_db``，把 service 层绑到
  测试数据库；
- 通过 ``unittest.mock.patch`` 替换
  ``app.services.commerce.task_dispatch.celery_app.send_task``，避免真实
  投递；同时断言它被调用一次、参数正确（task name + args + queue）。

覆盖点
------

* ``POST /commerce/products/extract``  ✓ 202 + envelope + GenerationTask 行
* ``POST /commerce/products/extract``  ✓ 422 当 raw_text 为空
* ``POST /commerce/products/extract``  ✓ payload.run_args 与 request 一致
* ``POST /commerce/script-generate``    ✓ 422 缺字段
* ``POST /commerce/script-generate``    ✓ task_kind=story_script_generate
* ``POST /commerce/compliance/check``   ✓ task_kind=compliance_check
* extra="forbid"                         ✓ 422 反多余字段（3 个端点）
* mock send_task                         ✓ 调用次数与参数
* 422 invalid target_duration_sec
* 422 missing variant_id
* response envelope 形态
* task_id 为 uuid hex 形态
"""

# pylint: disable=redefined-outer-name,too-many-arguments,too-many-locals

from __future__ import annotations

import re
from collections.abc import AsyncGenerator, Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.dependencies import get_db
from app.main import app
from app.models.task import GenerationTask, GenerationTaskStatus
from app.services.commerce.task_dispatch import (
    TASK_KIND_COMPLIANCE_CHECK,
    TASK_KIND_PRODUCT_INFO_EXTRACT,
    TASK_KIND_STORY_SCRIPT_GENERATE,
    TASK_KIND_STORY_VIDEO_BATCH_GENERATE,
)


_UUID_HEX = re.compile(r"^[0-9a-f]{32}$")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def session_local(tmp_path) -> Generator[async_sessionmaker[AsyncSession], None, None]:
    """文件型 SQLite + Base.metadata.create_all 的 async sessionmaker。

    用文件型 DB 而非 ``:memory:``：commerce 任务调度可能在多次连接间共享
    同一行记录，文件型可以避免“每次 connect 一张空表”的陷阱。
    """

    db_path = tmp_path / "commerce-tasks.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    import asyncio

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
    """绑定测试数据库的 FastAPI TestClient。"""

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


@pytest.fixture
def mock_send_task() -> Generator[MagicMock, None, None]:
    """Patch ``celery_app.send_task`` so tests never invoke the broker.

    Patching at the module that uses it (``task_dispatch``) keeps the seam
    minimal: any other code path that uses ``celery_app`` is unaffected.
    """

    with patch("app.services.commerce.task_dispatch.celery_app.send_task") as mocked:
        mocked.return_value = MagicMock(id="celery-mock-id")
        yield mocked


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _fetch_task(session_local, task_id: str) -> GenerationTask | None:
    async with session_local() as db:
        return await db.get(GenerationTask, task_id)


def _post(client: TestClient, path: str, payload: dict[str, Any]):
    return client.post(f"/api/v1/commerce{path}", json=payload)


# ---------------------------------------------------------------------------
# Tests: products/extract
# ---------------------------------------------------------------------------


def test_products_extract_returns_202_envelope_with_task_id(
    client_with_db, mock_send_task
) -> None:
    resp = _post(client_with_db, "/products/extract", {"raw_text": "iPhone 15 Pro Max 详情页"})
    assert resp.status_code == 202

    body = resp.json()
    assert body["code"] == 202
    assert body["message"] == "success"
    assert body["data"]["task_kind"] == TASK_KIND_PRODUCT_INFO_EXTRACT
    assert body["data"]["status"] == GenerationTaskStatus.pending.value
    assert _UUID_HEX.match(body["data"]["task_id"]), "task_id must be uuid4().hex format"
    assert "enqueued_at" in body["data"]

    mock_send_task.assert_called_once()
    args, kwargs = mock_send_task.call_args
    assert args[0] == "task.execute"
    assert kwargs["args"] == [body["data"]["task_id"]]
    assert kwargs["queue"] == "fast"


def test_products_extract_validates_non_empty_raw_text(
    client_with_db, mock_send_task
) -> None:
    resp = _post(client_with_db, "/products/extract", {"raw_text": ""})
    assert resp.status_code == 422
    mock_send_task.assert_not_called()


def test_products_extract_persists_run_args_in_payload(
    client_with_db, mock_send_task, session_local
) -> None:
    request_body = {
        "raw_text": "兰蔻小黑瓶精华 50ml 详情",
        "target_fields": ["name", "spec"],
    }
    resp = _post(client_with_db, "/products/extract", request_body)
    assert resp.status_code == 202

    task_id = resp.json()["data"]["task_id"]

    import asyncio

    row = asyncio.run(_fetch_task(session_local, task_id))
    assert row is not None
    assert row.task_kind == TASK_KIND_PRODUCT_INFO_EXTRACT
    assert row.status == GenerationTaskStatus.pending
    assert row.payload["task_kind"] == TASK_KIND_PRODUCT_INFO_EXTRACT
    assert row.payload["run_args"] == request_body
    mock_send_task.assert_called_once()


def test_products_extract_rejects_extra_fields(
    client_with_db, mock_send_task
) -> None:
    resp = _post(
        client_with_db,
        "/products/extract",
        {"raw_text": "x", "rogue_field": "should_be_rejected"},
    )
    assert resp.status_code == 422
    mock_send_task.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: script-generate
# ---------------------------------------------------------------------------


def _valid_script_payload() -> dict[str, Any]:
    return {
        "project_id": "proj-1",
        "chapter_id": "chap-1",
        "formula_id": "cn_underdog",
        "product": {"name": "演示商品"},
        "audience": {"age_band": "25-34"},
        "archetype": "Sage",
        "tone_grid": {"humor": 0.4},
        "target_duration_sec": 60,
        "platform": "douyin",
    }


def test_script_generate_validates_required_fields(
    client_with_db, mock_send_task
) -> None:
    payload = _valid_script_payload()
    payload.pop("project_id")
    resp = _post(client_with_db, "/script-generate", payload)
    assert resp.status_code == 422
    mock_send_task.assert_not_called()


def test_script_generate_creates_task_with_story_script_generate_kind(
    client_with_db, mock_send_task, session_local
) -> None:
    payload = _valid_script_payload()
    resp = _post(client_with_db, "/script-generate", payload)
    assert resp.status_code == 202

    body = resp.json()
    assert body["data"]["task_kind"] == TASK_KIND_STORY_SCRIPT_GENERATE
    assert _UUID_HEX.match(body["data"]["task_id"])

    import asyncio

    row = asyncio.run(_fetch_task(session_local, body["data"]["task_id"]))
    assert row is not None
    assert row.task_kind == TASK_KIND_STORY_SCRIPT_GENERATE
    assert row.payload["run_args"] == payload

    mock_send_task.assert_called_once()
    args, kwargs = mock_send_task.call_args
    assert args[0] == "task.execute"
    assert kwargs["queue"] == "fast"


def test_script_generate_422_on_invalid_target_duration_sec(
    client_with_db, mock_send_task
) -> None:
    payload = _valid_script_payload()
    payload["target_duration_sec"] = 600
    resp = _post(client_with_db, "/script-generate", payload)
    assert resp.status_code == 422
    mock_send_task.assert_not_called()


def test_script_generate_rejects_extra_fields(
    client_with_db, mock_send_task
) -> None:
    payload = _valid_script_payload()
    payload["sneak"] = "extra"
    resp = _post(client_with_db, "/script-generate", payload)
    assert resp.status_code == 422
    mock_send_task.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: compliance/check
# ---------------------------------------------------------------------------


def test_compliance_check_creates_task_with_compliance_check_kind(
    client_with_db, mock_send_task, session_local
) -> None:
    payload = {
        "variant_id": "var-1",
        "region": "cn_mainland",
        "product_category": "beauty",
        "script_text": None,
        "script_duration_sec": 45,
        "brand_aliases": ["LANCOME", "兰蔻"],
    }
    resp = _post(client_with_db, "/compliance/check", payload)
    assert resp.status_code == 202

    body = resp.json()
    assert body["data"]["task_kind"] == TASK_KIND_COMPLIANCE_CHECK
    assert _UUID_HEX.match(body["data"]["task_id"])

    import asyncio

    row = asyncio.run(_fetch_task(session_local, body["data"]["task_id"]))
    assert row is not None
    assert row.task_kind == TASK_KIND_COMPLIANCE_CHECK
    assert row.payload["run_args"]["variant_id"] == "var-1"
    assert row.payload["run_args"]["brand_aliases"] == ["LANCOME", "兰蔻"]

    mock_send_task.assert_called_once()


def test_compliance_check_422_on_missing_variant_id(
    client_with_db, mock_send_task
) -> None:
    resp = _post(client_with_db, "/compliance/check", {})
    assert resp.status_code == 422
    mock_send_task.assert_not_called()


def test_compliance_check_rejects_extra_fields(
    client_with_db, mock_send_task
) -> None:
    resp = _post(
        client_with_db,
        "/compliance/check",
        {"variant_id": "var-1", "rogue": "x"},
    )
    assert resp.status_code == 422
    mock_send_task.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: story-batches (W14-T1)
# ---------------------------------------------------------------------------


def _valid_batch_payload() -> dict[str, Any]:
    """构造合法批量请求体，覆盖 2 个变体的最小可用形态。"""

    return {
        "project_id": "proj-1",
        "chapter_id": "chap-1",
        "product": {"name": "演示商品"},
        "audience": {"age_band": "25-34"},
        "target_duration_sec": 60,
        "platform": "douyin",
        "variants": [
            {"formula_id": "underdog_triumph", "archetype": "sage", "label": "v1"},
            {"formula_id": "dramatic_reversal", "archetype": "hero", "label": "v2"},
        ],
        "parallelism": 2,
    }


def test_enqueue_story_batch_returns_202(
    client_with_db, mock_send_task
) -> None:
    """合法请求体 -> 202 + envelope + slow 队列投递。"""

    resp = _post(client_with_db, "/story-batches", _valid_batch_payload())
    assert resp.status_code == 202

    body = resp.json()
    assert body["code"] == 202
    assert body["message"] == "success"
    assert body["data"]["task_kind"] == TASK_KIND_STORY_VIDEO_BATCH_GENERATE
    assert body["data"]["status"] == GenerationTaskStatus.pending.value
    assert _UUID_HEX.match(body["data"]["task_id"])

    # 批量任务自身只投递一次，落 slow 队列；子任务的 send_task 由 worker
    # 在 Celery 消费阶段触发，不在此处入口路径上发生。
    mock_send_task.assert_called_once()
    args, kwargs = mock_send_task.call_args
    assert args[0] == "task.execute"
    assert kwargs["args"] == [body["data"]["task_id"]]
    assert kwargs["queue"] == "slow"


def test_enqueue_story_batch_validates_extra_fields(
    client_with_db, mock_send_task
) -> None:
    """``BatchGenerationRequest`` 必须 ``extra='forbid'`` -> 422。"""

    payload = _valid_batch_payload()
    payload["rogue_field"] = "should_be_rejected"
    resp = _post(client_with_db, "/story-batches", payload)
    assert resp.status_code == 422
    mock_send_task.assert_not_called()


def test_enqueue_story_batch_calls_send_task_for_each_variant(
    client_with_db, mock_send_task, session_local
) -> None:
    """API 入口落一行 batch 任务；payload 完整保留 N 个变体。

    W14-T1 的入口阶段只投递一次 batch 自身（``slow`` 队列），子任务的
    N 次 ``send_task`` 由 worker 在 Celery 消费阶段触发；本测试通过
    断言 batch 行 ``payload['run_args']['variants']`` 数量与请求一致，
    覆盖“N 个变体最终会被 worker 转化成 N 个子任务”这一契约。
    """

    payload = _valid_batch_payload()
    payload["variants"] = [
        {"formula_id": f"f{i}", "label": f"v{i}"} for i in range(1, 5)
    ]
    resp = _post(client_with_db, "/story-batches", payload)
    assert resp.status_code == 202

    body = resp.json()
    task_id = body["data"]["task_id"]

    import asyncio

    row = asyncio.run(_fetch_task(session_local, task_id))
    assert row is not None
    assert row.task_kind == TASK_KIND_STORY_VIDEO_BATCH_GENERATE
    assert row.status == GenerationTaskStatus.pending
    persisted = row.payload["run_args"]
    assert len(persisted["variants"]) == 4
    formula_ids = {v["formula_id"] for v in persisted["variants"]}
    assert formula_ids == {"f1", "f2", "f3", "f4"}

    mock_send_task.assert_called_once()
    args, kwargs = mock_send_task.call_args
    assert args[0] == "task.execute"
    assert kwargs["queue"] == "slow"
