"""``CommerceTaskDispatchService.enqueue_shot_subtitle_render`` 单元测试（P3 W18）。

覆盖（≥3 cases）：

1. ``enqueue_shot_subtitle_render`` 落 ``GenerationTask`` 行 + 投递 Celery，
   且队列默认走 ``fast``（与 TTS / ASR 对称）；
2. ``run_args`` 透传：``shot_id`` / ``style_id`` / ``word_timestamps`` /
   ``language_code`` / ``source`` 在 ``payload['run_args']`` 中保留原值；
3. ``TASK_KIND_SHOT_SUBTITLE_RENDER`` 常量与 worker 注册键一致。

测试架构与 ``test_tts_generate_dispatcher`` / ``test_asr_subtitle_generate_dispatcher``
同源：文件型 SQLite + Celery ``send_task`` mock。
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
    TASK_KIND_SHOT_SUBTITLE_RENDER,
    CommerceTaskDispatchService,
)
from app.services.studio.shot_subtitle_render_worker import (
    TASK_KIND as WORKER_TASK_KIND,
)


_UUID_HEX = re.compile(r"^[0-9a-f]{32}$")


@pytest.fixture
def session_local(tmp_path) -> Generator[async_sessionmaker[AsyncSession], None, None]:
    """文件型 SQLite + Base.metadata.create_all 的 async sessionmaker。"""

    db_path = tmp_path / "subtitle-dispatch.db"
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
    """Patch ``celery_app.send_task`` 让 dispatcher 不真投递 broker。"""

    with patch("app.services.commerce.task_dispatch.celery_app.send_task") as mocked:
        mocked.return_value = MagicMock(id="celery-mock-id")
        yield mocked


def test_task_kind_constant_matches_worker_registration() -> None:
    """``TASK_KIND_SHOT_SUBTITLE_RENDER`` 必须等于 worker 注册的 ``TASK_KIND``。"""

    assert (
        TASK_KIND_SHOT_SUBTITLE_RENDER
        == WORKER_TASK_KIND
        == "shot_subtitle_render"
    )


def test_enqueue_shot_subtitle_render_persists_row_and_publishes_to_fast_queue(
    session_local: async_sessionmaker[AsyncSession],
    mock_send_task: MagicMock,
) -> None:
    """落 ``GenerationTask`` 行 + commit 后 dispatch_after_commit(queue="fast")。

    W19b 契约：``enqueue_*`` 仅落表，``dispatch_after_commit`` 必须在
    ``await db.commit()`` 之后调用。
    """

    body: dict[str, Any] = {
        "shot_id": "shot-w18-x",
        "style_id": "douyin_default",
        "word_timestamps": [
            {"text": "你", "begin_ms": 0, "end_ms": 300},
            {"text": "好", "begin_ms": 300, "end_ms": 600},
        ],
        "language_code": "zh-CN",
        "source": "tts_word_timestamps",
    }

    async def _run():
        async with session_local() as db:
            service = CommerceTaskDispatchService(db)
            descriptor = await service.enqueue_shot_subtitle_render(body)
            await db.commit()
            service.dispatch_after_commit(descriptor)
            return descriptor

    descriptor = asyncio.run(_run())

    assert descriptor.task_kind == TASK_KIND_SHOT_SUBTITLE_RENDER
    assert descriptor.status == GenerationTaskStatus.pending.value
    assert _UUID_HEX.match(descriptor.task_id), "task_id must be uuid4().hex"
    assert descriptor.enqueued_at is not None

    mock_send_task.assert_called_once()
    args, kwargs = mock_send_task.call_args
    assert args[0] == "task.execute"
    assert kwargs["args"] == [descriptor.task_id]
    assert kwargs["queue"] == "fast", (
        "字幕渲染必须走 fast 队列，与 TTS / ASR 对称"
    )

    async def _fetch() -> GenerationTask | None:
        async with session_local() as db:
            return await db.get(GenerationTask, descriptor.task_id)

    row = asyncio.run(_fetch())
    assert row is not None
    assert row.task_kind == TASK_KIND_SHOT_SUBTITLE_RENDER
    assert row.status == GenerationTaskStatus.pending
    assert row.payload["task_kind"] == TASK_KIND_SHOT_SUBTITLE_RENDER
    assert row.payload["run_args"] == body


def test_enqueue_shot_subtitle_render_preserves_optional_fields(
    session_local: async_sessionmaker[AsyncSession],
    mock_send_task: MagicMock,
) -> None:
    """缺省 ``language_code`` / ``source`` 时仅透传必填项，dispatcher 不写默认。"""

    body: dict[str, Any] = {
        "shot_id": "shot-w18-y",
        "style_id": "tiktok_viral",
        "word_timestamps": [],
    }

    async def _run() -> str:
        async with session_local() as db:
            service = CommerceTaskDispatchService(db)
            descriptor = await service.enqueue_shot_subtitle_render(body)
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
    assert row.payload["run_args"] == body
    assert "language_code" not in row.payload["run_args"], (
        "dispatcher 不应自动注入 language_code 默认值"
    )
    assert "source" not in row.payload["run_args"], (
        "dispatcher 不应自动注入 source 默认值"
    )
