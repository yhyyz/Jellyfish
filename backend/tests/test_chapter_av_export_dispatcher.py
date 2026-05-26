"""``CommerceTaskDispatchService.enqueue_chapter_av_export`` 单元测试（P3 W19）。

覆盖（≥3 cases）：

1. 落 ``GenerationTask`` 行 + 投递 Celery slow 队列（与 chapter_av_plan 对齐）；
2. ``run_args`` 透传：``chapter_id`` / ``aspect`` / ``audio_strategy_override``
   在 ``payload['run_args']`` 中保留原值；
3. ``TASK_KIND_CHAPTER_AV_EXPORT`` 常量与 worker 注册键一致。

测试架构与 ``test_asr_subtitle_generate_dispatcher`` 同源：文件型 SQLite +
Celery ``send_task`` mock。
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
from app.services.commerce.task_dispatch import (
    TASK_KIND_CHAPTER_AV_EXPORT,
    CommerceTaskDispatchService,
)
from app.services.studio.chapter_av_export_task import (
    TASK_KIND as WORKER_TASK_KIND,
)


_UUID_HEX = re.compile(r"^[0-9a-f]{32}$")


@pytest.fixture
def session_local(tmp_path) -> Generator[async_sessionmaker[AsyncSession], None, None]:
    """文件型 SQLite + Base.metadata.create_all。"""

    db_path = tmp_path / "av-export-dispatch.db"
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
    """``TASK_KIND_CHAPTER_AV_EXPORT`` 必须等于 worker ``TASK_KIND``。"""

    assert (
        TASK_KIND_CHAPTER_AV_EXPORT
        == WORKER_TASK_KIND
        == "chapter_av_export"
    )


def test_enqueue_chapter_av_export_persists_row_and_publishes_to_slow_queue(
    session_local: async_sessionmaker[AsyncSession],
    mock_send_task: MagicMock,
) -> None:
    """落 ``GenerationTask`` 行 + send_task(queue="slow")。

    与 chapter_av_plan 对齐：章节级合成属分钟级长任务，必须走 ``slow``
    队列避免与 fast 队列上的分钟级 worker 争抢消费者。
    """

    body: dict[str, Any] = {
        "chapter_id": "chap-w19-x",
        "aspect": "9:16",
    }

    async def _run() -> dict[str, Any]:
        async with session_local() as db:
            service = CommerceTaskDispatchService(db)
            payload = await service.enqueue_chapter_av_export(body)
            await db.commit()
            return payload

    payload = asyncio.run(_run())

    assert payload["task_kind"] == TASK_KIND_CHAPTER_AV_EXPORT
    assert payload["status"] == GenerationTaskStatus.pending.value
    assert _UUID_HEX.match(payload["task_id"]), "task_id must be uuid4().hex"

    mock_send_task.assert_called_once()
    args, kwargs = mock_send_task.call_args
    assert args[0] == "task.execute"
    assert kwargs["args"] == [payload["task_id"]]
    assert kwargs["queue"] == "slow", (
        "章节级 AV 合成必须走 slow 队列，与 chapter_av_plan 对齐"
    )

    async def _fetch() -> GenerationTask | None:
        async with session_local() as db:
            return await db.get(GenerationTask, payload["task_id"])

    row = asyncio.run(_fetch())
    assert row is not None
    assert row.task_kind == TASK_KIND_CHAPTER_AV_EXPORT
    assert row.status == GenerationTaskStatus.pending
    assert row.payload["task_kind"] == TASK_KIND_CHAPTER_AV_EXPORT
    assert row.payload["run_args"] == body


def test_enqueue_chapter_av_export_preserves_audio_strategy_override(
    session_local: async_sessionmaker[AsyncSession],
    mock_send_task: MagicMock,
) -> None:
    """``audio_strategy_override`` 等可选字段原样透传到 run_args。"""

    body: dict[str, Any] = {
        "chapter_id": "chap-w19-y",
        "aspect": "16:9",
        "audio_strategy_override": "keep_native",
    }

    async def _run() -> str:
        async with session_local() as db:
            service = CommerceTaskDispatchService(db)
            payload = await service.enqueue_chapter_av_export(body)
            await db.commit()
            return payload["task_id"]

    task_id = asyncio.run(_run())
    mock_send_task.assert_called_once()

    async def _fetch() -> GenerationTask | None:
        async with session_local() as db:
            return await db.get(GenerationTask, task_id)

    row = asyncio.run(_fetch())
    assert row is not None
    assert row.payload["run_args"] == body


def test_enqueue_chapter_av_export_minimal_body_only_chapter_id(
    session_local: async_sessionmaker[AsyncSession],
    mock_send_task: MagicMock,
) -> None:
    """缺省 ``aspect`` / ``override`` 时仅透传 ``chapter_id``，dispatcher 不写默认值。"""

    body: dict[str, Any] = {"chapter_id": "chap-w19-z"}

    async def _run() -> str:
        async with session_local() as db:
            service = CommerceTaskDispatchService(db)
            payload = await service.enqueue_chapter_av_export(body)
            await db.commit()
            return payload["task_id"]

    task_id = asyncio.run(_run())
    mock_send_task.assert_called_once()

    async def _fetch() -> GenerationTask | None:
        async with session_local() as db:
            return await db.get(GenerationTask, task_id)

    row = asyncio.run(_fetch())
    assert row is not None
    assert row.payload["run_args"] == {"chapter_id": "chap-w19-z"}
    assert "aspect" not in row.payload["run_args"], (
        "dispatcher 不应自动注入 aspect 默认值；worker 内部解析时再兜底"
    )
