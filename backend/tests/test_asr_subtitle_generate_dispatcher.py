"""``CommerceTaskDispatchService.enqueue_asr_subtitle_generate`` 单元测试

（P3 W17 收尾，Decision D 修订）。

覆盖（≥3 cases）：

1. ``enqueue_asr_subtitle_generate`` 落 ``GenerationTask`` 行 + 投递 Celery，
   且队列默认走 ``fast``（与 ``tts_generate`` 对称）；
2. ``run_args`` 透传：``video_file_id`` / ``language_hints`` 在
   ``payload['run_args']`` 中保留原值；
3. ``TASK_KIND_ASR_SUBTITLE_GENERATE`` 常量与 worker 注册键一致。

测试架构与 ``test_tts_generate_dispatcher.py`` 同源：文件型 SQLite + Celery
``send_task`` mock，但绕开 FastAPI，直接构造 service 并调用方法。
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
    TASK_KIND_ASR_SUBTITLE_GENERATE,
    CommerceTaskDispatchService,
)
from app.services.studio.asr_subtitle_generate_worker import (
    TASK_KIND as WORKER_TASK_KIND,
)


_UUID_HEX = re.compile(r"^[0-9a-f]{32}$")


@pytest.fixture
def session_local(tmp_path) -> Generator[async_sessionmaker[AsyncSession], None, None]:
    """文件型 SQLite + Base.metadata.create_all 的 async sessionmaker。"""

    db_path = tmp_path / "asr-dispatch.db"
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
    """``TASK_KIND_ASR_SUBTITLE_GENERATE`` 必须等于 worker 注册的 ``TASK_KIND``。"""

    assert (
        TASK_KIND_ASR_SUBTITLE_GENERATE
        == WORKER_TASK_KIND
        == "asr_subtitle_generate"
    )


def test_enqueue_asr_subtitle_generate_persists_row_and_publishes_to_fast_queue(
    session_local: async_sessionmaker[AsyncSession],
    mock_send_task: MagicMock,
) -> None:
    """落 ``GenerationTask`` 行 + commit 后 dispatch_after_commit(queue="fast")。

    与 TTS 对称：ASR 字幕反推属分钟级，必须走 ``fast`` 队列，不应跑到
    ``slow`` 队列与视频生成 worker 争抢消费者。

    W19b 契约：``enqueue_*`` 仅落表，``dispatch_after_commit`` 必须在
    ``await db.commit()`` 之后调用，避免 worker 拿到消息时行尚未 commit。
    """

    body: dict[str, Any] = {
        "video_file_id": "file-shot-x-keep-native",
        "language_hints": ["zh", "en"],
    }

    async def _run() -> tuple[Any, list[bool]]:
        async with session_local() as db:
            service = CommerceTaskDispatchService(db)
            descriptor = await service.enqueue_asr_subtitle_generate(body)
            send_called_before_commit = mock_send_task.called
            await db.commit()
            send_called_after_commit_before_dispatch = mock_send_task.called
            service.dispatch_after_commit(descriptor)
            return descriptor, [
                send_called_before_commit,
                send_called_after_commit_before_dispatch,
            ]

    descriptor, ordering_flags = asyncio.run(_run())

    assert ordering_flags == [False, False], (
        "enqueue_asr_subtitle_generate / commit 都不应触发 send_task；"
        "只有 dispatch_after_commit 才允许投递 broker。"
    )
    assert descriptor.task_kind == TASK_KIND_ASR_SUBTITLE_GENERATE
    assert descriptor.status == GenerationTaskStatus.pending.value
    assert _UUID_HEX.match(descriptor.task_id), "task_id must be uuid4().hex"
    assert descriptor.enqueued_at is not None

    mock_send_task.assert_called_once()
    args, kwargs = mock_send_task.call_args
    assert args[0] == "task.execute"
    assert kwargs["args"] == [descriptor.task_id]
    assert kwargs["queue"] == "fast", (
        "ASR 字幕反推必须走 fast 队列，与 TTS 对称"
    )

    # 任务行已经落地，并保留原始 run_args。
    async def _fetch() -> GenerationTask | None:
        async with session_local() as db:
            return await db.get(GenerationTask, descriptor.task_id)

    row = asyncio.run(_fetch())
    assert row is not None
    assert row.task_kind == TASK_KIND_ASR_SUBTITLE_GENERATE
    assert row.status == GenerationTaskStatus.pending
    assert row.payload["task_kind"] == TASK_KIND_ASR_SUBTITLE_GENERATE
    assert row.payload["run_args"] == body


def test_enqueue_asr_subtitle_generate_preserves_optional_fields(
    session_local: async_sessionmaker[AsyncSession],
    mock_send_task: MagicMock,
) -> None:
    """缺省 ``language_hints`` 时仍然原样透传 ``video_file_id``。

    worker 自身会兜底默认 hints，dispatcher 不应自作主张写入默认值，
    保证 dispatch 层契约最小化。
    """

    body: dict[str, Any] = {
        "video_file_id": "file-shot-y-keep-native",
    }

    async def _run() -> str:
        async with session_local() as db:
            service = CommerceTaskDispatchService(db)
            descriptor = await service.enqueue_asr_subtitle_generate(body)
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
    assert row.payload["run_args"] == {"video_file_id": "file-shot-y-keep-native"}
    assert "language_hints" not in row.payload["run_args"], (
        "dispatcher 不应自动注入默认 language_hints"
    )
