"""W19b 回归测试：commerce dispatcher 必须先 commit、再发 broker 消息。

为什么存在
----------

历史实现把“flush GenerationTask 行”和“celery_app.send_task”写在同一个
``_enqueue`` 内部方法里：第 3 步 flush 之后立刻 send_task。``fast`` 队列
上的 worker 会几乎瞬间拉到消息并 ``run_task_celery``，里面 ``db.get`` 拿到
``None``（外层事务尚未 commit），worker 静默 ACK，行永久 ``pending``。

W19b 把 :class:`CommerceTaskDispatchService` 的入队拆成两段：

- ``enqueue_*``：仅落表 + flush，**不发** broker 消息；
- ``dispatch_after_commit(descriptor)``：在调用方 commit 之后才发消息。

本测试钉住这条契约：

1. ``enqueue_asr_subtitle_generate`` 仅落表，``send_task`` 不应该被调；
2. ``await db.commit()`` 之后，``send_task`` 仍未被调（commit 不会触发
   隐式 dispatch）；
3. ``dispatch_after_commit(descriptor)`` 才真正调用 ``send_task``，且
   ``args=[descriptor.task_id]`` / ``queue=descriptor.queue``；
4. ``dispatch_after_commit`` 内部 broker 异常被吞，不向上抛——commit 已
   完成，不应再回滚。

测试架构与 ``test_asr_subtitle_generate_dispatcher`` 同源：文件型 SQLite +
celery ``send_task`` patch。
"""

# pylint: disable=redefined-outer-name

from __future__ import annotations

import asyncio
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.services.commerce.task_dispatch import CommerceTaskDispatchService


@pytest.fixture
def session_local(tmp_path) -> Generator[async_sessionmaker[AsyncSession], None, None]:
    """文件型 SQLite + Base.metadata.create_all 的 async sessionmaker。"""

    db_path = tmp_path / "chain-dispatch-after-commit.db"
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


def test_enqueue_does_not_send_task_until_dispatch_after_commit(
    session_local: async_sessionmaker[AsyncSession],
    mock_send_task: MagicMock,
) -> None:
    """W19b 核心契约：enqueue / commit 都不发消息，仅 dispatch_after_commit 才发。

    钉住 4 个时间点的 ``send_task.call_count``：

    - ``after enqueue``: 0（仅落表，绝不发消息）；
    - ``after commit``: 0（commit 不会触发隐式 dispatch）；
    - ``after dispatch_after_commit``: 1（真正向 broker 投递）；
    - 投递时 ``args=[descriptor.task_id]`` 且 ``queue == descriptor.queue``。

    若有人未来在 ``commit`` 上挂 after_commit 钩子自动 fire，本测试会捕获
    “after commit”阶段的非零 call_count 异常。
    """

    body = {"video_file_id": "file-after-commit"}

    async def _scenario():
        async with session_local() as db:
            service = CommerceTaskDispatchService(db)
            descriptor = await service.enqueue_asr_subtitle_generate(body)
            after_enqueue = mock_send_task.call_count
            await db.commit()
            after_commit = mock_send_task.call_count
            service.dispatch_after_commit(descriptor)
            after_dispatch = mock_send_task.call_count
            return descriptor, after_enqueue, after_commit, after_dispatch

    descriptor, after_enqueue, after_commit, after_dispatch = asyncio.run(_scenario())

    assert after_enqueue == 0, (
        "enqueue_* 应仅落表，不应发 broker 消息；当前在 enqueue 后已被调用"
    )
    assert after_commit == 0, (
        "commit 不应隐式触发 dispatch；如果非零说明被人加了 after_commit 钩子"
    )
    assert after_dispatch == 1, (
        "dispatch_after_commit 必须显式调用 send_task 一次"
    )

    args, kwargs = mock_send_task.call_args
    assert args[0] == "task.execute"
    assert kwargs["args"] == [descriptor.task_id]
    assert kwargs["queue"] == descriptor.queue


def test_dispatch_after_commit_swallows_broker_failure(
    session_local: async_sessionmaker[AsyncSession],
    mock_send_task: MagicMock,
) -> None:
    """broker 临时不可用时 dispatch_after_commit 应吞异常 + 记 warning，不向上抛。

    为什么这条契约重要：到这一步 GenerationTask 行已经 commit 落地，业务
    上已经“接受了请求”，不能再因为 broker 网络瞬断回滚已成功的状态。
    本测试模拟 send_task 抛异常的情形，确保 dispatch_after_commit 静默
    返回，调用方继续执行后续逻辑。
    """

    mock_send_task.side_effect = RuntimeError("broker temporarily unavailable")
    body = {"video_file_id": "file-broker-fail"}

    async def _scenario():
        async with session_local() as db:
            service = CommerceTaskDispatchService(db)
            descriptor = await service.enqueue_asr_subtitle_generate(body)
            await db.commit()
            service.dispatch_after_commit(descriptor)
            return descriptor

    descriptor = asyncio.run(_scenario())

    mock_send_task.assert_called_once()
    assert descriptor.task_id, "descriptor 仍然有效，dispatch 失败不应造成上游异常"
