"""``tts_generate_worker`` 功能性测试（P3 W17 T17-5）。

测试覆盖（≥7 cases）：

1. ``task_executor_registry.resolve("tts_generate")`` 命中本 worker 工厂。
2. 工厂构造的 executor ``timeout_seconds`` 等于 plan 约定的 300s。
3. 空 ``text`` → 立刻 ``ValueError``，不产生任何 session 工作。
4. ``voice_pack_id`` 不存在 → 抛出明确错误，状态置 ``failed``。
5. cache miss happy-path：调用 ``DashScopeTtsApiAdapter.synthesize``，
   写 FileItem + tts_cache 行 + ``TtsResult(cache_hit=False)``。
6. cache hit：预置 ``tts_cache`` 行，``synthesize`` 不被调用，
   ``TtsResult(cache_hit=True)`` + ``hit_count`` 自增。
7. 取消（adapter 调用前）：``cancel_if_requested_async`` 短路返回，
   ``synthesize`` 不被调用。
8. 取消（adapter 调用后）：合成完成但取消已请求，不再写 cache，
   状态保持 cancelled。
9. adapter 抛错：原会话 rollback，独立会话写 ``failed`` + ``error``。

测试架构：
    使用文件型 SQLite + ``Base.metadata.create_all`` 真实建表，
    通过 ``monkeypatch`` 把 worker 模块内的 ``async_session_maker``
    替换为绑定到测试数据库的 ``async_sessionmaker``；
    DashScope 适配器 + provider 解析 helper 用 mock 替换，
    避免真实 WebSocket / S3 / DB Provider 行依赖。
"""

# pylint: disable=redefined-outer-name,too-many-arguments,too-many-locals

from __future__ import annotations

import asyncio
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.contracts.tts import (
    TtsCacheKey,
    TtsRequest,
    TtsResult,
    TtsWordTimestamp,
)
from app.core.db import Base
from app.models.studio import FileItem
from app.models.task import GenerationDeliveryMode, GenerationTask, GenerationTaskStatus
from app.models.types import VoiceGender, VoiceProvider
from app.models.voice_pack import TtsCache, VoicePack
from app.services.studio import tts_generate_worker as worker_mod
from app.services.studio.tts_generate_worker import (
    DEFAULT_TIMEOUT_SECONDS,
    TASK_KIND,
    build_tts_generate_executor,
    run_tts_generate_task,
)
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_registry import task_executor_registry


# ---------------------------------------------------------------------------
# Fixtures：sqlite 后端 + worker async_session_maker patch
# ---------------------------------------------------------------------------


_VOICE_PACK_ID = "cosyvoice_v2_longxiaochun"
_PROVIDER_VOICE_ID = "longxiaochun_v2"


@pytest.fixture
def session_local(tmp_path) -> Generator[async_sessionmaker[AsyncSession], None, None]:
    """文件型 SQLite + Base.metadata.create_all 的 async sessionmaker。"""

    db_path = tmp_path / "tts-worker.db"
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
def fake_audio_bytes() -> bytes:
    """合成结果占位字节序列：仅用于断言长度与 minio 上传调用。"""

    # 4KB 的合成 MP3 占位字节，避免真实 codec 依赖。
    return b"\xff\xfb\x90\x00" * 1024


@pytest.fixture
def fake_word_timestamps() -> list[TtsWordTimestamp]:
    """合成结果占位字级时间戳：跨多句以便 duration_ms 取最大尾时。"""

    return [
        TtsWordTimestamp(text="你好", begin_ms=0, end_ms=320),
        TtsWordTimestamp(text="世界", begin_ms=320, end_ms=820),
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_voice_pack(
    session_local: async_sessionmaker[AsyncSession],
    *,
    pack_id: str = _VOICE_PACK_ID,
    provider_voice_id: str = _PROVIDER_VOICE_ID,
) -> None:
    """落一行系统级 VoicePack 行，供 cache miss 路径加载 provider_voice_id。"""

    async with session_local() as db:
        db.add(
            VoicePack(
                id=pack_id,
                name="龙小淳-test",
                provider=VoiceProvider.aliyun_cosyvoice,
                provider_voice_id=provider_voice_id,
                language_code="zh-CN",
                gender=VoiceGender.female,
                description="test",
                default_speed=1.0,
                is_system=True,
                sort_order=0,
            )
        )
        await db.commit()


async def _seed_generation_task(
    session_local: async_sessionmaker[AsyncSession],
    *,
    task_id: str,
    task_kind: str = TASK_KIND,
    cancel_requested: bool = False,
) -> None:
    """落一行 ``GenerationTask`` 行，供 worker 状态机更新。"""

    async with session_local() as db:
        db.add(
            GenerationTask(
                id=task_id,
                mode=GenerationDeliveryMode.async_polling,
                task_kind=task_kind,
                status=GenerationTaskStatus.pending,
                progress=0,
                payload={"task_kind": task_kind, "run_args": {}},
                result=None,
                error="",
                cancel_requested=cancel_requested,
            )
        )
        await db.commit()


async def _seed_audio_file(
    session_local: async_sessionmaker[AsyncSession],
    *,
    file_id: str = "file-cached-audio",
) -> None:
    """落一行 FileItem，供 cache hit 路径直接复用 audio_file_id。"""

    async with session_local() as db:
        from app.models.studio import FileType  # noqa: WPS433 - 局部导入避免顶部噪声

        db.add(
            FileItem(
                id=file_id,
                type=FileType.audio,
                name="cached-audio",
                thumbnail="",
                tags=[],
                storage_key="files/cached-audio.mp3",
            )
        )
        await db.commit()


async def _seed_cache_row(
    session_local: async_sessionmaker[AsyncSession],
    *,
    cache_key: str,
    audio_file_id: str,
    voice_pack_id: str = _VOICE_PACK_ID,
    duration_ms: int = 1234,
    hit_count: int = 5,
) -> None:
    """预置一条 ``tts_cache`` 行，模拟此前已经合成过的命中记录。"""

    async with session_local() as db:
        db.add(
            TtsCache(
                cache_key=cache_key,
                voice_pack_id=voice_pack_id,
                text_preview="cached text",
                speed=1.0,
                audio_file_id=audio_file_id,
                duration_ms=duration_ms,
                word_timestamps=[
                    {"text": "你好", "begin_ms": 0, "end_ms": 500},
                ],
                hit_count=hit_count,
            )
        )
        await db.commit()


def _install_no_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    """``cancel_if_requested_async`` 永远返回 False，避免触发取消短路。"""

    async def _never(*_: Any, **__: Any) -> bool:
        return False

    monkeypatch.setattr(worker_mod, "cancel_if_requested_async", _never)


def _install_fake_provider_resolver(
    monkeypatch: pytest.MonkeyPatch,
    *,
    api_key: str = "sk-test-tts-key",
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


def _install_fake_adapter(
    monkeypatch: pytest.MonkeyPatch,
    *,
    audio_bytes: bytes,
    word_timestamps: list[TtsWordTimestamp],
    side_effect: Exception | None = None,
) -> AsyncMock:
    """把 ``DashScopeTtsApiAdapter.synthesize`` 替换为可断言的 AsyncMock。"""

    if side_effect is not None:
        synth_mock = AsyncMock(side_effect=side_effect)
    else:
        synth_mock = AsyncMock(return_value=(audio_bytes, list(word_timestamps)))

    fake_instance = MagicMock(name="DashScopeTtsApiAdapter_instance")
    fake_instance.synthesize = synth_mock
    fake_cls = MagicMock(name="DashScopeTtsApiAdapter_cls", return_value=fake_instance)
    monkeypatch.setattr(worker_mod, "DashScopeTtsApiAdapter", fake_cls)
    return synth_mock


def _install_fake_audio_persister(
    monkeypatch: pytest.MonkeyPatch,
    *,
    file_id: str = "file-fresh-audio",
    storage_key: str = "tts-audio/fresh.mp3",
) -> AsyncMock:
    """绕过 minio 真实上传：直接落一条 FileItem 并返回。"""

    from app.models.studio import FileType  # noqa: WPS433 - 局部导入避免顶部噪声

    async def _persist(
        session: AsyncSession,
        *,
        audio_bytes: bytes,
        audio_format: str,
        voice_pack_id: str,
        cache_key: str,
    ) -> FileItem:
        # 触摸入参以避免 pylint 抱怨未使用形参；fake 不真实读取它们的内容。
        _ = (audio_bytes, audio_format, voice_pack_id, cache_key)
        file_obj = FileItem(
            id=file_id,
            type=FileType.audio,
            name="tts-fresh",
            thumbnail="https://example.test/audio.mp3",
            tags=[],
            storage_key=storage_key,
        )
        session.add(file_obj)
        await session.flush()
        return file_obj

    mock = AsyncMock(side_effect=_persist)
    monkeypatch.setattr(worker_mod, "_persist_tts_audio", mock)
    return mock


# ---------------------------------------------------------------------------
# 注册元数据
# ---------------------------------------------------------------------------


def test_executor_registered_with_tts_generate_task_kind() -> None:
    """``task_executor_registry.resolve("tts_generate")`` 应命中本 worker。"""

    executor = task_executor_registry.resolve(TASK_KIND)
    assert isinstance(executor, AbstractAsyncDelegatingExecutor)
    assert executor.task_kind == TASK_KIND


def test_executor_timeout_set_to_300s() -> None:
    """``timeout_seconds`` 必须保持 plan 约定的 300.0s。"""

    executor = build_tts_generate_executor()
    assert executor.timeout_seconds == DEFAULT_TIMEOUT_SECONDS == 300.0
    assert executor.task_kind == TASK_KIND == "tts_generate"


# ---------------------------------------------------------------------------
# 输入校验
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_raises_on_empty_text() -> None:
    """空 ``text`` 应在进入 session 前立刻抛 ``ValueError``。"""

    with pytest.raises(ValueError, match="text"):
        await run_tts_generate_task("task-empty", {"voice_pack_id": _VOICE_PACK_ID, "text": "  "})


@pytest.mark.asyncio
async def test_runner_raises_on_missing_voice_pack_id() -> None:
    """缺失 ``voice_pack_id`` 应同样早抛。"""

    with pytest.raises(ValueError, match="voice_pack_id"):
        await run_tts_generate_task("task-novp", {"text": "你好"})


# ---------------------------------------------------------------------------
# Cache miss happy-path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_cache_miss_creates_file_and_cache_row(
    patched_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    fake_audio_bytes: bytes,
    fake_word_timestamps: list[TtsWordTimestamp],
) -> None:
    """cache miss → 调 synthesize → 落 FileItem + tts_cache 行 + cache_hit=False。"""

    task_id = "task-miss"
    text = "你好世界"
    await _seed_generation_task(patched_session, task_id=task_id)
    await _seed_voice_pack(patched_session)
    _install_no_cancel(monkeypatch)
    _install_fake_provider_resolver(monkeypatch)
    synth_mock = _install_fake_adapter(
        monkeypatch,
        audio_bytes=fake_audio_bytes,
        word_timestamps=fake_word_timestamps,
    )
    persist_mock = _install_fake_audio_persister(monkeypatch, file_id="file-miss-audio")

    await run_tts_generate_task(
        task_id,
        {
            "text": text,
            "voice_pack_id": _VOICE_PACK_ID,
            "speed": 1.0,
            "audio_format": "mp3",
            "enable_word_timestamps": True,
        },
    )

    synth_mock.assert_awaited_once()
    persist_mock.assert_awaited_once()

    # synthesize 收到正确 TtsRequest（provider_voice_id 来自 VoicePack）。
    await_args = synth_mock.await_args
    assert await_args is not None
    synth_kwargs = await_args.kwargs
    assert isinstance(synth_kwargs["input_"], TtsRequest)
    assert synth_kwargs["input_"].voice_pack_id == _VOICE_PACK_ID
    assert synth_kwargs["input_"].provider_voice_id == _PROVIDER_VOICE_ID
    assert synth_kwargs["input_"].text == text

    expected_key = TtsCacheKey(text=text, voice_pack_id=_VOICE_PACK_ID, speed=1.0).to_hash()

    async with patched_session() as db:
        task_row = await db.get(GenerationTask, task_id)
        assert task_row is not None
        assert task_row.status == GenerationTaskStatus.succeeded
        assert task_row.progress == 100
        result = TtsResult.model_validate(task_row.result)
        assert result.cache_hit is False
        assert result.audio_file_id == "file-miss-audio"
        assert result.duration_ms == 820  # max end_ms in fake_word_timestamps
        assert len(result.word_timestamps) == 2

        cache_row = (
            await db.execute(select(TtsCache).where(TtsCache.cache_key == expected_key))
        ).scalars().first()
        assert cache_row is not None
        assert cache_row.audio_file_id == "file-miss-audio"
        assert cache_row.voice_pack_id == _VOICE_PACK_ID
        assert cache_row.duration_ms == 820
        assert cache_row.hit_count == 0
        assert cache_row.text_preview.startswith("你好")


# ---------------------------------------------------------------------------
# Cache hit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_cache_hit_skips_synthesize_and_increments_hit_count(
    patched_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    fake_audio_bytes: bytes,
    fake_word_timestamps: list[TtsWordTimestamp],
) -> None:
    """命中 cache → 不调 synthesize → cache_hit=True + hit_count 自增。"""

    task_id = "task-hit"
    text = "重复合成的台词"
    cache_key = TtsCacheKey(text=text, voice_pack_id=_VOICE_PACK_ID, speed=1.0).to_hash()

    await _seed_generation_task(patched_session, task_id=task_id)
    await _seed_voice_pack(patched_session)
    await _seed_audio_file(patched_session, file_id="file-cached-audio")
    await _seed_cache_row(
        patched_session,
        cache_key=cache_key,
        audio_file_id="file-cached-audio",
        duration_ms=1234,
        hit_count=5,
    )

    _install_no_cancel(monkeypatch)
    _install_fake_provider_resolver(monkeypatch)
    synth_mock = _install_fake_adapter(
        monkeypatch,
        audio_bytes=fake_audio_bytes,
        word_timestamps=fake_word_timestamps,
    )
    persist_mock = _install_fake_audio_persister(monkeypatch)

    await run_tts_generate_task(
        task_id,
        {"text": text, "voice_pack_id": _VOICE_PACK_ID},
    )

    synth_mock.assert_not_awaited()
    persist_mock.assert_not_awaited()

    async with patched_session() as db:
        task_row = await db.get(GenerationTask, task_id)
        assert task_row is not None
        assert task_row.status == GenerationTaskStatus.succeeded
        result = TtsResult.model_validate(task_row.result)
        assert result.cache_hit is True
        assert result.audio_file_id == "file-cached-audio"
        assert result.duration_ms == 1234

        cache_row = (
            await db.execute(select(TtsCache).where(TtsCache.cache_key == cache_key))
        ).scalars().first()
        assert cache_row is not None
        assert cache_row.hit_count == 6


# ---------------------------------------------------------------------------
# Voice pack 不存在
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_marks_failed_when_voice_pack_missing(
    patched_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    fake_audio_bytes: bytes,
    fake_word_timestamps: list[TtsWordTimestamp],
) -> None:
    """``voice_pack_id`` 在 DB 中不存在 → 任务置 ``failed`` 并向上抛错。"""

    task_id = "task-vpmissing"
    await _seed_generation_task(patched_session, task_id=task_id)
    _install_no_cancel(monkeypatch)
    _install_fake_provider_resolver(monkeypatch)
    synth_mock = _install_fake_adapter(
        monkeypatch,
        audio_bytes=fake_audio_bytes,
        word_timestamps=fake_word_timestamps,
    )

    with pytest.raises(LookupError, match="voice_pack"):
        await run_tts_generate_task(
            task_id,
            {"text": "你好", "voice_pack_id": "no-such-voice-pack"},
        )

    synth_mock.assert_not_awaited()
    async with patched_session() as db:
        task_row = await db.get(GenerationTask, task_id)
        assert task_row is not None
        assert task_row.status == GenerationTaskStatus.failed
        assert "voice_pack" in (task_row.error or "")


# ---------------------------------------------------------------------------
# 取消（adapter 调用前 / 后）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_cancels_before_adapter_call(
    patched_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    fake_audio_bytes: bytes,
    fake_word_timestamps: list[TtsWordTimestamp],
) -> None:
    """``cancel_if_requested_async`` 第一次返回 True → synthesize 不被调用。"""

    task_id = "task-cancel-before"
    await _seed_generation_task(patched_session, task_id=task_id, cancel_requested=True)
    await _seed_voice_pack(patched_session)
    _install_fake_provider_resolver(monkeypatch)
    synth_mock = _install_fake_adapter(
        monkeypatch,
        audio_bytes=fake_audio_bytes,
        word_timestamps=fake_word_timestamps,
    )

    # cancel_if_requested_async：第一次（before_execute）就返回 True。
    cancel_calls = {"count": 0}

    async def _cancel_first(*_: Any, **__: Any) -> bool:
        cancel_calls["count"] += 1
        return cancel_calls["count"] == 1

    monkeypatch.setattr(worker_mod, "cancel_if_requested_async", _cancel_first)

    await run_tts_generate_task(
        task_id,
        {"text": "你好", "voice_pack_id": _VOICE_PACK_ID},
    )

    synth_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_runner_cancels_after_adapter_call_skips_persist(
    patched_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    fake_audio_bytes: bytes,
    fake_word_timestamps: list[TtsWordTimestamp],
) -> None:
    """``cancel_if_requested_async`` 在 synthesize 之后返回 True → 不写 cache 行。"""

    task_id = "task-cancel-after"
    text = "中途取消"
    await _seed_generation_task(patched_session, task_id=task_id)
    await _seed_voice_pack(patched_session)
    _install_fake_provider_resolver(monkeypatch)
    synth_mock = _install_fake_adapter(
        monkeypatch,
        audio_bytes=fake_audio_bytes,
        word_timestamps=fake_word_timestamps,
    )
    persist_mock = _install_fake_audio_persister(monkeypatch)

    # 第一次（before_execute）= False、第二次（after_execute）= True
    cancel_calls = {"count": 0}

    async def _cancel_after(*_: Any, **__: Any) -> bool:
        cancel_calls["count"] += 1
        return cancel_calls["count"] >= 2

    monkeypatch.setattr(worker_mod, "cancel_if_requested_async", _cancel_after)

    await run_tts_generate_task(
        task_id,
        {"text": text, "voice_pack_id": _VOICE_PACK_ID},
    )

    synth_mock.assert_awaited_once()
    persist_mock.assert_not_awaited()

    cache_key = TtsCacheKey(text=text, voice_pack_id=_VOICE_PACK_ID, speed=1.0).to_hash()
    async with patched_session() as db:
        cache_row = (
            await db.execute(select(TtsCache).where(TtsCache.cache_key == cache_key))
        ).scalars().first()
        assert cache_row is None  # 取消后不应写入 cache


# ---------------------------------------------------------------------------
# adapter 抛错
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_marks_failed_when_adapter_raises(
    patched_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``synthesize`` 抛 ``RuntimeError`` → 状态 failed + error 文本被记录。"""

    task_id = "task-adapterfail"
    await _seed_generation_task(patched_session, task_id=task_id)
    await _seed_voice_pack(patched_session)
    _install_no_cancel(monkeypatch)
    _install_fake_provider_resolver(monkeypatch)
    _install_fake_adapter(
        monkeypatch,
        audio_bytes=b"",
        word_timestamps=[],
        side_effect=RuntimeError("DashScope WS 503"),
    )

    with pytest.raises(RuntimeError, match="DashScope WS 503"):
        await run_tts_generate_task(
            task_id,
            {"text": "服务异常", "voice_pack_id": _VOICE_PACK_ID},
        )

    async with patched_session() as db:
        task_row = await db.get(GenerationTask, task_id)
        assert task_row is not None
        assert task_row.status == GenerationTaskStatus.failed
        assert "DashScope WS 503" in (task_row.error or "")
