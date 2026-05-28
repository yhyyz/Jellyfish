"""W29-T5 voice_clone_poll_task 单元测试。

覆盖：
    1. DEPLOYING ×2 -> OK：voice_pack.clone_status 最终落到 ``ready`` +
       ``cloned_at`` 非空；任务状态 ``succeeded``。
    2. UNDEPLOYED：voice_pack.clone_status 最终落到 ``failed`` +
       description 末尾追加失败原因；任务状态 ``succeeded``（轮询自身完成）。
    3. 连续 DEPLOYING MAX_ATTEMPTS 次：超时退路把 voice_pack.clone_status
       置 ``failed``。
    4. enqueue dispatch：``task_executor_registry.resolve("voice_clone_poll")``
       返回正确执行器；``CommerceTaskDispatchService.enqueue_voice_clone_poll``
       链路存在且不发 broker 消息（W19b 契约）。
"""

# pylint: disable=protected-access,redefined-outer-name,too-few-public-methods

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 必须 import 全部模型以确保 Base.metadata 拥有完整 schema。
import app.models.api_quota  # noqa: F401  pylint: disable=unused-import
import app.models.commerce_assets  # noqa: F401  pylint: disable=unused-import
import app.models.compliance  # noqa: F401  pylint: disable=unused-import
import app.models.llm  # noqa: F401  pylint: disable=unused-import
import app.models.story_formula  # noqa: F401  pylint: disable=unused-import
import app.models.studio  # noqa: F401  pylint: disable=unused-import
import app.models.task  # noqa: F401  pylint: disable=unused-import
import app.models.task_links  # noqa: F401  pylint: disable=unused-import
import app.models.voice_pack  # noqa: F401  pylint: disable=unused-import

from app.core.db import Base
from app.core.task_manager.types import TaskStatus
from app.models.task import GenerationDeliveryMode, GenerationTask, GenerationTaskStatus
from app.models.types import VoiceCloneStatus, VoiceGender, VoiceProvider, VoiceRegion
from app.models.voice_pack import VoicePack
from app.services.commerce.task_dispatch import (
    CommerceTaskDispatchService,
    TASK_KIND_VOICE_CLONE_POLL,
)
from app.services.studio import voice_clone_poll_task as poll_module
from app.services.studio.voice_clone_poll_task import (
    DEFAULT_TIMEOUT_SECONDS,
    MAX_ATTEMPTS,
    TASK_KIND,
    run_voice_clone_poll_task,
)
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_registry import task_executor_registry


# ---------------------------------------------------------------------------
# Fixtures：file-backed SQLite + 预置 GenerationTask + VoicePack
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    """构造 file-backed SQLite 引擎，让 worker 内 ``async_session_maker()`` 能看到同一份数据库。"""
    db_path = tmp_path / "voice-clone-poll.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_local = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield session_local
    await engine.dispose()


@pytest_asyncio.fixture
async def patched_session_maker(session_factory, monkeypatch):
    """把 worker 内部的 ``async_session_maker`` 指向同一个 file-backed 引擎。"""
    monkeypatch.setattr(poll_module, "async_session_maker", session_factory)
    return session_factory


async def _seed_task_and_voice_pack(
    session_factory,
    *,
    task_id: str = "t-poll-1",
    voice_pack_id: str = "clone_test1",
) -> None:
    """在数据库里塞一条 GenerationTask + VoicePack 行。"""
    async with session_factory() as session:
        session.add(
            GenerationTask(
                id=task_id,
                mode=GenerationDeliveryMode.async_polling,
                task_kind=TASK_KIND,
                status=GenerationTaskStatus.pending,
                progress=0,
                payload={
                    "task_kind": TASK_KIND,
                    "run_args": {"voice_pack_id": voice_pack_id},
                },
                result=None,
                error="",
            )
        )
        session.add(
            VoicePack(
                id=voice_pack_id,
                name="测试克隆音色",
                provider=VoiceProvider.aliyun_cosyvoice,
                provider_voice_id="cosyvoice-v3.5-plus-myvoice-test",
                language_code="zh-CN",
                gender=VoiceGender.neutral,
                description="",
                default_speed=1.0,
                is_system=False,
                sort_order=1000,
                target_model="cosyvoice-v3.5-plus",
                region=VoiceRegion.cn_beijing,
                clone_status=VoiceCloneStatus.deploying,
                sample_audio_oss_key="voice-clone-samples/test.wav",
                cloned_at=None,
            )
        )
        await session.commit()


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch):
    """所有测试都 stub 掉 ``asyncio.sleep`` 让循环立即推进。"""

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(poll_module.asyncio, "sleep", _no_sleep)


def _stub_query(monkeypatch: pytest.MonkeyPatch, sequence: list[tuple[VoiceCloneStatus, str | None]]) -> None:
    """把 ``query_clone_status`` 替换为按 ``sequence`` 顺序返回值的迭代器。"""
    iterator = iter(sequence)

    async def _fake_query(*, voice_id: str, region: VoiceRegion):
        try:
            return next(iterator)
        except StopIteration:
            return VoiceCloneStatus.deploying, None

    monkeypatch.setattr(poll_module, "query_clone_status", _fake_query)


# ---------------------------------------------------------------------------
# 三个 lifecycle case
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_succeeds_after_two_deploying_then_ok(
    session_factory, patched_session_maker, monkeypatch
) -> None:
    """DEPLOYING ×2 -> OK：voice_pack 最终为 ready，任务 succeeded。"""
    await _seed_task_and_voice_pack(session_factory)
    _stub_query(
        monkeypatch,
        [
            (VoiceCloneStatus.deploying, None),
            (VoiceCloneStatus.deploying, None),
            (VoiceCloneStatus.ready, None),
        ],
    )

    await run_voice_clone_poll_task("t-poll-1", {"voice_pack_id": "clone_test1"})

    async with session_factory() as session:
        voice_pack = await session.get(VoicePack, "clone_test1")
        assert voice_pack is not None
        assert voice_pack.clone_status == VoiceCloneStatus.ready
        assert voice_pack.cloned_at is not None

        task = await session.get(GenerationTask, "t-poll-1")
        assert task is not None
        assert task.status == GenerationTaskStatus.succeeded
        assert task.progress == 100
        assert task.result is not None
        assert task.result["clone_status"] == "ready"


@pytest.mark.asyncio
async def test_poll_terminates_on_undeployed(
    session_factory, patched_session_maker, monkeypatch
) -> None:
    """DEPLOYING -> UNDEPLOYED：voice_pack 落 failed + description 含失败原因。"""
    await _seed_task_and_voice_pack(session_factory)
    _stub_query(
        monkeypatch,
        [
            (VoiceCloneStatus.deploying, None),
            (
                VoiceCloneStatus.failed,
                "DashScope returned UNDEPLOYED",
            ),
        ],
    )

    await run_voice_clone_poll_task("t-poll-1", {"voice_pack_id": "clone_test1"})

    async with session_factory() as session:
        voice_pack = await session.get(VoicePack, "clone_test1")
        assert voice_pack is not None
        assert voice_pack.clone_status == VoiceCloneStatus.failed
        assert voice_pack.cloned_at is None
        assert "[clone_failed]" in (voice_pack.description or "")
        assert "UNDEPLOYED" in (voice_pack.description or "")

        task = await session.get(GenerationTask, "t-poll-1")
        assert task is not None
        assert task.status == GenerationTaskStatus.succeeded
        assert task.result is not None
        assert task.result["clone_status"] == "failed"
        assert task.result["failure_reason"] == "DashScope returned UNDEPLOYED"


@pytest.mark.asyncio
async def test_poll_times_out_after_max_attempts(
    session_factory, patched_session_maker, monkeypatch
) -> None:
    """连续 DEPLOYING MAX_ATTEMPTS 次：超时退路落 failed。"""
    await _seed_task_and_voice_pack(session_factory)
    _stub_query(
        monkeypatch,
        [(VoiceCloneStatus.deploying, None)] * (MAX_ATTEMPTS + 5),
    )

    await run_voice_clone_poll_task("t-poll-1", {"voice_pack_id": "clone_test1"})

    async with session_factory() as session:
        voice_pack = await session.get(VoicePack, "clone_test1")
        assert voice_pack is not None
        assert voice_pack.clone_status == VoiceCloneStatus.failed

        task = await session.get(GenerationTask, "t-poll-1")
        assert task is not None
        assert task.status == GenerationTaskStatus.succeeded
        assert task.result is not None
        assert task.result["clone_status"] == "failed"
        assert "timed out" in (task.result.get("failure_reason") or "")


# ---------------------------------------------------------------------------
# enqueue dispatch + executor registry
# ---------------------------------------------------------------------------


def test_executor_registry_has_voice_clone_poll() -> None:
    """``task_executor_registry`` 必须能 resolve voice_clone_poll 执行器。"""
    executor = task_executor_registry.resolve("voice_clone_poll")
    assert isinstance(executor, AbstractAsyncDelegatingExecutor)
    assert executor.task_kind == "voice_clone_poll"
    assert executor.timeout_seconds == DEFAULT_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_enqueue_voice_clone_poll_does_not_send_broker(
    session_factory, monkeypatch
) -> None:
    """``enqueue_voice_clone_poll`` 必须只 flush DB 行，不主动发 broker 消息。"""
    sent: list[Any] = []
    from app.services.commerce import task_dispatch as dispatch_module

    def _fake_send_task(*args: Any, **kwargs: Any) -> None:
        sent.append((args, kwargs))

    monkeypatch.setattr(
        dispatch_module.celery_app, "send_task", _fake_send_task
    )

    async with session_factory() as session:
        dispatcher = CommerceTaskDispatchService(session)
        descriptor = await dispatcher.enqueue_voice_clone_poll(
            {"voice_pack_id": "clone_test1"}
        )
        assert descriptor.task_kind == TASK_KIND_VOICE_CLONE_POLL
        assert descriptor.queue == "fast"
        assert descriptor.status == "pending"

        # W19b 契约：只 flush，未 commit；W19b 修订：未 dispatch broker。
        assert sent == [], (
            "enqueue_voice_clone_poll must NOT send broker message before commit"
        )

        await session.commit()
        # 验证行已落库
        row = await session.get(GenerationTask, descriptor.task_id)
        assert row is not None
        assert row.task_kind == TASK_KIND_VOICE_CLONE_POLL

        dispatcher.dispatch_after_commit(descriptor)
        assert len(sent) == 1, "dispatch_after_commit must trigger send_task"
