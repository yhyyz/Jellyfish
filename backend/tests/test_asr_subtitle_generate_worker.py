"""``asr_subtitle_generate_worker`` 功能性测试（P3 W17 收尾，Decision D 修订）。

测试覆盖（≥6 cases）：

1. ``task_executor_registry.resolve("asr_subtitle_generate")`` 命中本 worker 工厂；
2. 工厂构造的 executor ``timeout_seconds`` 等于 plan 约定的 600s；
3. 空 ``video_file_id`` → 立刻 ``ValueError``；
4. ``video_file_id`` 不存在 → 抛 LookupError，状态置 ``failed``；
5. happy-path：调用 ``DashScopeTtsApiAdapter.estimate_audio_via_asr``，
   写 ``GenerationTask.result`` 含 ``word_timestamps`` / ``duration_ms`` /
   ``audio_url`` / ``language_hints``，状态推进 ``succeeded``；
6. 取消（adapter 调用前）：``cancel_if_requested_async`` 短路，
   ``estimate_audio_via_asr`` 不被调用；
7. 取消（adapter 调用后）：合成完成但取消已请求，不再写 result；
8. adapter 抛错：原会话 rollback，独立会话写 ``failed`` + ``error``。

测试架构与 ``test_tts_generate_worker.py`` 同源：文件型 SQLite + ``Base.metadata.create_all``
+ monkeypatch async_session_maker；DashScope adapter / provider resolver / minio 全部 mock。
"""

# pylint: disable=redefined-outer-name,too-many-arguments,too-many-locals

from __future__ import annotations

import asyncio
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.contracts.tts import TtsWordTimestamp
from app.core.db import Base
from app.core.storage import StoredFileInfo
from app.models.studio import FileItem, FileType
from app.models.task import GenerationDeliveryMode, GenerationTask, GenerationTaskStatus
from app.services.studio import asr_subtitle_generate_worker as worker_mod
from app.services.studio.asr_subtitle_generate_worker import (
    DEFAULT_TIMEOUT_SECONDS,
    TASK_KIND,
    build_asr_subtitle_generate_executor,
    run_asr_subtitle_generate_task,
)
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_registry import task_executor_registry


# ---------------------------------------------------------------------------
# Fixtures：sqlite 后端 + worker async_session_maker patch
# ---------------------------------------------------------------------------


_VIDEO_FILE_ID = "file-asr-source-video"
_PUBLIC_AUDIO_URL = "https://cdn.example.com/tmp/keep-native-shot.mp4"


@pytest.fixture
def session_local(tmp_path) -> Generator[async_sessionmaker[AsyncSession], None, None]:
    """文件型 SQLite + Base.metadata.create_all 的 async sessionmaker。"""

    db_path = tmp_path / "asr-subtitle-worker.db"
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
def patched_session(
    session_local: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> async_sessionmaker[AsyncSession]:
    """把 worker 模块内的 ``async_session_maker`` 替换为测试 sessionmaker。"""

    monkeypatch.setattr(worker_mod, "async_session_maker", session_local)
    return session_local


@pytest.fixture
def fake_word_timestamps() -> list[TtsWordTimestamp]:
    """Paraformer-v2 反推产物占位：跨多句以便 duration_ms 取最大尾时。"""

    return [
        TtsWordTimestamp(text="哥们儿", begin_ms=0, end_ms=520),
        TtsWordTimestamp(text="这", begin_ms=520, end_ms=720),
        TtsWordTimestamp(text="睡衣", begin_ms=720, end_ms=1180),
        TtsWordTimestamp(text="不错", begin_ms=1180, end_ms=1740),
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_video_file(
    session_local: async_sessionmaker[AsyncSession],
    *,
    file_id: str = _VIDEO_FILE_ID,
    storage_key: str = "generated-videos/shots/shot-x/keep-native.mp4",
) -> None:
    """落一行 FileItem，模拟 keep_native 路径已有的视频源。"""

    async with session_local() as db:
        db.add(
            FileItem(
                id=file_id,
                type=FileType.video,
                name="keep-native-source",
                thumbnail="",
                tags=[],
                storage_key=storage_key,
            )
        )
        await db.commit()


async def _seed_generation_task(
    session_local: async_sessionmaker[AsyncSession],
    *,
    task_id: str,
    cancel_requested: bool = False,
) -> None:
    """落一行 ``GenerationTask`` 行，供 worker 状态机更新。"""

    async with session_local() as db:
        db.add(
            GenerationTask(
                id=task_id,
                mode=GenerationDeliveryMode.async_polling,
                task_kind=TASK_KIND,
                status=GenerationTaskStatus.pending,
                progress=0,
                payload={"task_kind": TASK_KIND, "run_args": {}},
                result=None,
                error="",
                cancel_requested=cancel_requested,
            )
        )
        await db.commit()


def _install_no_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    """``cancel_if_requested_async`` 永远返回 False，避免触发取消短路。"""

    async def _never(*_: Any, **__: Any) -> bool:
        return False

    monkeypatch.setattr(worker_mod, "cancel_if_requested_async", _never)


def _install_always_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    """让首次 cancel 检查就返回 True，模拟"被运营点了取消"。"""

    async def _always(*_: Any, **__: Any) -> bool:
        return True

    monkeypatch.setattr(worker_mod, "cancel_if_requested_async", _always)


def _install_fake_provider_resolver(
    monkeypatch: pytest.MonkeyPatch,
    *,
    api_key: str = "sk-test-asr-key",
) -> AsyncMock:
    """跳过真实 Provider 行查询，直接返回固定的 ``ProviderConfig``。"""

    from app.core.contracts.provider import ProviderConfig

    async def _resolve(*_: Any, **__: Any) -> ProviderConfig:
        return ProviderConfig(
            provider="aliyun_bailian",
            api_key=api_key,
            base_url=None,
        )

    mock = AsyncMock(side_effect=_resolve)
    monkeypatch.setattr(worker_mod, "_resolve_dashscope_provider_config", mock)
    return mock


def _install_fake_storage(
    monkeypatch: pytest.MonkeyPatch,
    *,
    url: str = _PUBLIC_AUDIO_URL,
) -> None:
    """跳过真实 S3 head_object，直接返回固定的 ``StoredFileInfo``。"""

    async def _get_info(*, key: str) -> StoredFileInfo:
        return StoredFileInfo(
            key=key,
            url=url,
            size=1024,
            content_type="video/mp4",
        )

    monkeypatch.setattr(worker_mod.storage, "get_file_info", _get_info)


def _install_fake_adapter(
    monkeypatch: pytest.MonkeyPatch,
    *,
    word_timestamps: list[TtsWordTimestamp],
) -> AsyncMock:
    """把 ``DashScopeTtsApiAdapter.estimate_audio_via_asr`` 替换为 AsyncMock。

    返回的 mock 可以让测试断言 ``call_args``，验证传入的 cfg / audio_url / timeout。
    """

    estimate_mock = AsyncMock(return_value=word_timestamps)

    class _FakeAdapter:
        """最小化伪 adapter；只暴露 estimate_audio_via_asr 用于本测试。"""

        async def estimate_audio_via_asr(self, **kwargs: Any) -> list[TtsWordTimestamp]:
            return await estimate_mock(**kwargs)

    monkeypatch.setattr(worker_mod, "DashScopeTtsApiAdapter", _FakeAdapter)
    return estimate_mock


# ---------------------------------------------------------------------------
# 1. 注册元数据
# ---------------------------------------------------------------------------


def test_executor_registered_with_asr_subtitle_generate_task_kind() -> None:
    """``task_executor_registry.resolve("asr_subtitle_generate")`` 应命中本 worker。"""

    executor = task_executor_registry.resolve(TASK_KIND)
    assert isinstance(executor, AbstractAsyncDelegatingExecutor)
    assert executor.task_kind == TASK_KIND


def test_executor_timeout_set_to_600s() -> None:
    """fast 队列超时上限：600s（与 Paraformer-v2 adapter 默认 timeout 对齐）。"""

    executor = build_asr_subtitle_generate_executor()
    assert executor.timeout_seconds == DEFAULT_TIMEOUT_SECONDS == 600.0
    assert executor.task_kind == TASK_KIND == "asr_subtitle_generate"


# ---------------------------------------------------------------------------
# 2. run_args 校验
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_rejects_empty_video_file_id() -> None:
    """空 ``video_file_id`` 必须立刻抛 ``ValueError``，不进入 session 工作。"""

    with pytest.raises(ValueError, match="video_file_id"):
        await run_asr_subtitle_generate_task("task-x", {"video_file_id": ""})


@pytest.mark.asyncio
async def test_runner_marks_failed_when_file_id_not_found(
    patched_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``video_file_id`` 不存在：worker 走 hotfix-4 失败路径，状态置 ``failed``。"""

    _install_no_cancel(monkeypatch)
    _install_fake_provider_resolver(monkeypatch)

    task_id = "task-missing-file"
    await _seed_generation_task(patched_session, task_id=task_id)

    with pytest.raises(LookupError):
        await run_asr_subtitle_generate_task(
            task_id, {"video_file_id": "file-not-exist"}
        )

    async with patched_session() as db:
        task_row = await db.get(GenerationTask, task_id)
        assert task_row is not None
        assert task_row.status == GenerationTaskStatus.failed
        assert "file-not-exist" in (task_row.error or "")


# ---------------------------------------------------------------------------
# 3. happy-path：完整 ASR 反推
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_invokes_paraformer_and_writes_word_timestamps(
    patched_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    fake_word_timestamps: list[TtsWordTimestamp],
) -> None:
    """happy-path：调用 estimate_audio_via_asr，写 result + succeeded。

    断言要点：
    - adapter 被调用且参数正确（cfg / audio_url / timeout）；
    - result 字段完整且 duration_ms == 最大 end_ms；
    - 状态推进到 ``succeeded``、progress=100。
    """

    _install_no_cancel(monkeypatch)
    _install_fake_provider_resolver(monkeypatch, api_key="sk-asr-test")
    _install_fake_storage(monkeypatch, url=_PUBLIC_AUDIO_URL)
    estimate_mock = _install_fake_adapter(
        monkeypatch, word_timestamps=fake_word_timestamps
    )

    await _seed_video_file(patched_session)

    task_id = "task-asr-happy"
    await _seed_generation_task(patched_session, task_id=task_id)

    await run_asr_subtitle_generate_task(
        task_id,
        {
            "video_file_id": _VIDEO_FILE_ID,
            "language_hints": ["zh", "en"],
        },
    )

    estimate_mock.assert_awaited_once()
    call_kwargs = estimate_mock.await_args.kwargs
    assert call_kwargs["audio_url"] == _PUBLIC_AUDIO_URL
    assert call_kwargs["timeout_s"] == DEFAULT_TIMEOUT_SECONDS
    cfg = call_kwargs["cfg"]
    assert cfg.provider == "aliyun_bailian"
    assert cfg.api_key == "sk-asr-test"

    async with patched_session() as db:
        task_row = await db.get(GenerationTask, task_id)
        assert task_row is not None
        assert task_row.status == GenerationTaskStatus.succeeded
        assert task_row.progress == 100
        assert isinstance(task_row.result, dict)
        result = task_row.result
        assert result["source_file_id"] == _VIDEO_FILE_ID
        assert result["audio_url"] == _PUBLIC_AUDIO_URL
        assert result["language_hints"] == ["zh", "en"]
        assert result["duration_ms"] == 1740
        words = result["word_timestamps"]
        assert isinstance(words, list) and len(words) == 4
        assert words[0]["text"] == "哥们儿"
        assert words[-1]["end_ms"] == 1740


@pytest.mark.asyncio
async def test_runner_uses_default_language_hints_when_not_provided(
    patched_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    fake_word_timestamps: list[TtsWordTimestamp],
) -> None:
    """run_args 缺省 language_hints：worker 应回填 ``["zh", "en"]`` 默认值。"""

    _install_no_cancel(monkeypatch)
    _install_fake_provider_resolver(monkeypatch)
    _install_fake_storage(monkeypatch)
    _install_fake_adapter(monkeypatch, word_timestamps=fake_word_timestamps)

    await _seed_video_file(patched_session)

    task_id = "task-asr-default-hints"
    await _seed_generation_task(patched_session, task_id=task_id)

    await run_asr_subtitle_generate_task(
        task_id, {"video_file_id": _VIDEO_FILE_ID}
    )

    async with patched_session() as db:
        task_row = await db.get(GenerationTask, task_id)
        assert task_row is not None
        assert task_row.status == GenerationTaskStatus.succeeded
        assert task_row.result["language_hints"] == ["zh", "en"]


# ---------------------------------------------------------------------------
# 4. cancel checkpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_short_circuits_on_cancel_before_adapter_call(
    patched_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    fake_word_timestamps: list[TtsWordTimestamp],
) -> None:
    """首次 cancel 检查为 True 时，adapter 不应被调用。"""

    _install_always_cancel(monkeypatch)
    _install_fake_provider_resolver(monkeypatch)
    _install_fake_storage(monkeypatch)
    estimate_mock = _install_fake_adapter(
        monkeypatch, word_timestamps=fake_word_timestamps
    )

    await _seed_video_file(patched_session)

    task_id = "task-asr-cancel-before"
    await _seed_generation_task(patched_session, task_id=task_id, cancel_requested=True)

    await run_asr_subtitle_generate_task(
        task_id, {"video_file_id": _VIDEO_FILE_ID}
    )

    estimate_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# 5. adapter 抛错：rollback + failed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_handles_adapter_exception_with_rollback_and_failed_status(
    patched_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """adapter 抛错时：原会话 rollback，独立会话写 ``failed`` + 错误信息。"""

    _install_no_cancel(monkeypatch)
    _install_fake_provider_resolver(monkeypatch)
    _install_fake_storage(monkeypatch)

    class _BoomAdapter:
        async def estimate_audio_via_asr(self, **_: Any) -> list[TtsWordTimestamp]:
            raise RuntimeError("dashscope paraformer 502 bad gateway")

    monkeypatch.setattr(worker_mod, "DashScopeTtsApiAdapter", _BoomAdapter)

    await _seed_video_file(patched_session)

    task_id = "task-asr-boom"
    await _seed_generation_task(patched_session, task_id=task_id)

    with pytest.raises(RuntimeError, match="502"):
        await run_asr_subtitle_generate_task(
            task_id, {"video_file_id": _VIDEO_FILE_ID}
        )

    async with patched_session() as db:
        task_row = await db.get(GenerationTask, task_id)
        assert task_row is not None
        assert task_row.status == GenerationTaskStatus.failed
        assert "502" in (task_row.error or "")
        assert task_row.result is None
