"""``CommerceTaskDispatchService.enqueue_commerce_export`` 单元测试（W23-T2）。

覆盖（≥3 cases）：

1. ``test_task_kind_constant_matches_worker_registration``：常量与 worker 同源。
2. ``test_route_enqueues_with_slow_queue``：落 ``GenerationTask`` 行 + Celery
   ``apply_async/send_task`` 的 ``queue="slow"`` 必须被设置。
3. ``test_enqueue_commerce_export_preserves_run_args``：``variant_id`` /
   ``preset_id`` 原样透传。

测试架构：文件型 SQLite + Celery ``send_task`` mock，与
``test_chapter_av_export_dispatcher`` 同模板。
"""

# pylint: disable=redefined-outer-name

from __future__ import annotations

import asyncio
import re
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.models.task import GenerationTask, GenerationTaskStatus
from app.services.commerce.commerce_export_worker import TASK_KIND as WORKER_TASK_KIND
from app.services.commerce.task_dispatch import (
    TASK_KIND_COMMERCE_EXPORT,
    CommerceTaskDispatchService,
)


_UUID_HEX = re.compile(r"^[0-9a-f]{32}$")


@pytest.fixture
def session_local(tmp_path) -> Generator[async_sessionmaker[AsyncSession], None, None]:
    """文件型 SQLite + Base.metadata.create_all。"""

    db_path = tmp_path / "commerce-export-dispatch.db"
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
def mock_send_task() -> Generator[MagicMock, None, None]:
    with patch("app.services.commerce.task_dispatch.celery_app.send_task") as mocked:
        mocked.return_value = MagicMock(id="celery-mock-id")
        yield mocked


def test_task_kind_constant_matches_worker_registration() -> None:
    """``TASK_KIND_COMMERCE_EXPORT`` 必须等于 worker ``TASK_KIND``。"""

    assert (
        TASK_KIND_COMMERCE_EXPORT
        == WORKER_TASK_KIND
        == "commerce_export"
    )


def test_route_enqueues_with_slow_queue(
    session_local: async_sessionmaker[AsyncSession],
    mock_send_task: MagicMock,
) -> None:
    """commerce_export 必须走 ``slow`` 队列（与 chapter_av_* 系列对齐）。"""

    body: dict[str, Any] = {
        "variant_id": "var-w23-x",
        "preset_id": "douyin_default",
    }

    async def _run():
        async with session_local() as db:
            service = CommerceTaskDispatchService(db)
            descriptor = await service.enqueue_commerce_export(body)
            await db.commit()
            service.dispatch_after_commit(descriptor)
            return descriptor

    descriptor = asyncio.run(_run())

    assert descriptor.task_kind == TASK_KIND_COMMERCE_EXPORT
    assert descriptor.status == GenerationTaskStatus.pending.value
    assert _UUID_HEX.match(descriptor.task_id), "task_id must be uuid4().hex"

    mock_send_task.assert_called_once()
    args, kwargs = mock_send_task.call_args
    assert args[0] == "task.execute"
    assert kwargs["args"] == [descriptor.task_id]
    assert kwargs["queue"] == "slow", (
        "commerce_export 必须走 slow 队列，避免与 fast 队列上的分钟级 worker 争抢消费者"
    )


def test_enqueue_commerce_export_preserves_run_args(
    session_local: async_sessionmaker[AsyncSession],
    mock_send_task: MagicMock,
) -> None:
    """``variant_id`` / ``preset_id`` 必须原样透传到 ``payload['run_args']``。"""

    body: dict[str, Any] = {
        "variant_id": "var-y",
        "preset_id": "tiktok_default",
    }

    async def _run() -> str:
        async with session_local() as db:
            service = CommerceTaskDispatchService(db)
            descriptor = await service.enqueue_commerce_export(body)
            await db.commit()
            service.dispatch_after_commit(descriptor)
            return descriptor.task_id

    task_id = asyncio.run(_run())
    mock_send_task.assert_called_once()

    async def _fetch() -> GenerationTask | None:
        async with session_local() as db:
            return await db.get(GenerationTask, task_id)

    row = asyncio.run(_fetch())
    assert row is not None
    assert row.task_kind == TASK_KIND_COMMERCE_EXPORT
    assert row.status == GenerationTaskStatus.pending
    assert row.payload["task_kind"] == TASK_KIND_COMMERCE_EXPORT
    assert row.payload["run_args"] == body
