"""W19b 回归测试：ASR worker 成功后链式派发 ``shot_subtitle_render``。

为什么存在
----------

历史 ASR worker 是叶子节点：写 ``word_timestamps`` 到 result 后即结束，
``keep_native`` 路径的前端必须再发一次 ``POST /commerce/shot-subtitle-render``
才能拿到 .ass 字幕。这与 ``silent_with_tts`` 路径有 ``chapter_av_planner``
编排形成不对称的客户端工作流。

W19b（B3/B6）让 ASR worker 自行链式派发：

- result 中带上 ``shot_id``（B6）；
- 写一行 :class:`GenerationTaskLink`（resource_type=subtitle / relation_type=shot）；
- ASR 主任务 commit 之后再开新 session 调
  :py:meth:`CommerceTaskDispatchService.enqueue_shot_subtitle_render` +
  ``commit`` + ``dispatch_after_commit``，严格遵循 W19b commit-before-dispatch
  契约；
- 链式派发任意异常都仅记录 warning，不向上抛——ASR 主任务已 commit，
  下游失败不应回滚已成功的状态。

本测试验证以上行为：

1. ASR happy-path：ASR row succeeded → result 含 shot_id + word_timestamps；
2. ``GenerationTaskLink`` 行已写入（task_id ↔ shot_id）；
3. NEW ``shot_subtitle_render`` row 已落库（status=pending），且 run_args
   含 shot_id / style_id / source=asr_paraformer_v2；
4. send_task 被调用 1 次（只有 chain dispatch 投递，因为 ASR 主任务的
   send_task 由外层 video worker 投递，不由 ASR worker 自身投递）；
5. 缺 shot_id 时降级到 legacy 行为：不写 GenerationTaskLink，不链式派发。
"""

# pylint: disable=redefined-outer-name,too-many-arguments,too-many-locals

from __future__ import annotations

import asyncio
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.contracts.tts import TtsWordTimestamp
from app.core.db import Base
from app.core.storage import StoredFileInfo
from app.models.studio import FileItem, FileType
from app.models.task import GenerationDeliveryMode, GenerationTask, GenerationTaskStatus
from app.models.task_links import GenerationTaskLink
from app.services.studio import asr_subtitle_generate_worker as worker_mod
from app.services.studio.asr_subtitle_generate_worker import (
    run_asr_subtitle_generate_task,
)


_VIDEO_FILE_ID = "file-asr-chain-source"
_PUBLIC_AUDIO_URL = "https://cdn.example.com/tmp/keep-native-chain.mp4"
_SHOT_ID = "shot-asr-chain"
_STYLE_ID = "douyin_default"


@pytest.fixture
def session_local(tmp_path) -> Generator[async_sessionmaker[AsyncSession], None, None]:
    """文件型 SQLite + Base.metadata.create_all 的 async sessionmaker。"""

    db_path = tmp_path / "asr-chain-into-render.db"
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
    """把 worker 模块的 ``async_session_maker`` 替换为测试 sessionmaker。

    ASR worker 的链式派发在主 session 关闭后开了新的 session，本 fixture
    把模块级 :data:`worker_mod.async_session_maker` 整体替换，覆盖主路径
    + 链式路径两处。
    """

    monkeypatch.setattr(worker_mod, "async_session_maker", session_local)
    return session_local


@pytest.fixture
def fake_word_timestamps() -> list[TtsWordTimestamp]:
    """Paraformer-v2 反推产物占位：跨多句以便 duration_ms 取最大尾时。"""

    return [
        TtsWordTimestamp(text="今天", begin_ms=0, end_ms=420),
        TtsWordTimestamp(text="天气", begin_ms=420, end_ms=820),
        TtsWordTimestamp(text="不错", begin_ms=820, end_ms=1280),
    ]


async def _seed_video_file(
    session_local: async_sessionmaker[AsyncSession],
    *,
    file_id: str = _VIDEO_FILE_ID,
) -> None:
    """落一行 FileItem，模拟 keep_native 路径已有的视频源。"""

    async with session_local() as db:
        db.add(
            FileItem(
                id=file_id,
                type=FileType.video,
                name="keep-native-chain-source",
                thumbnail="",
                tags=[],
                storage_key=f"generated-videos/{file_id}.mp4",
            )
        )
        await db.commit()


async def _seed_generation_task(
    session_local: async_sessionmaker[AsyncSession],
    *,
    task_id: str,
) -> None:
    """落一行 ``GenerationTask`` 行，供 ASR worker 状态机更新。"""

    async with session_local() as db:
        db.add(
            GenerationTask(
                id=task_id,
                mode=GenerationDeliveryMode.async_polling,
                task_kind="asr_subtitle_generate",
                status=GenerationTaskStatus.pending,
                progress=0,
                payload={"task_kind": "asr_subtitle_generate", "run_args": {}},
                result=None,
                error="",
            )
        )
        await db.commit()


def _install_common_mocks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    word_timestamps: list[TtsWordTimestamp],
) -> AsyncMock:
    """统一 patch：cancel 永远 False、provider/storage mock、Paraformer adapter mock。

    Returns:
        Paraformer ``estimate_audio_via_asr`` 的 AsyncMock。
    """

    async def _never(*_: Any, **__: Any) -> bool:
        return False

    monkeypatch.setattr(worker_mod, "cancel_if_requested_async", _never)

    from app.core.contracts.provider import ProviderConfig

    async def _resolve(*_: Any, **__: Any) -> ProviderConfig:
        return ProviderConfig(
            provider="aliyun_bailian", api_key="sk-test-asr-chain", base_url=None
        )

    monkeypatch.setattr(worker_mod, "_resolve_dashscope_provider_config", _resolve)

    async def _get_info(*, key: str) -> StoredFileInfo:
        return StoredFileInfo(
            key=key, url=_PUBLIC_AUDIO_URL, size=2048, content_type="video/mp4"
        )

    monkeypatch.setattr(worker_mod.storage, "get_file_info", _get_info)

    estimate_mock = AsyncMock(return_value=word_timestamps)

    class _FakeAdapter:
        async def estimate_audio_via_asr(self, **kwargs: Any) -> list[TtsWordTimestamp]:
            return await estimate_mock(**kwargs)

    monkeypatch.setattr(worker_mod, "DashScopeTtsApiAdapter", _FakeAdapter)
    return estimate_mock


def test_asr_success_chains_into_shot_subtitle_render(
    patched_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    fake_word_timestamps: list[TtsWordTimestamp],
) -> None:
    """ASR happy-path → 写 task_link、result 带 shot_id、链式派发 shot_subtitle_render。

    断言：

    1. ASR row succeeded + result 含 ``shot_id`` / ``word_timestamps``；
    2. ``GenerationTaskLink`` 已写入（task_id ↔ shot_id）；
    3. 新建 ``shot_subtitle_render`` row 落库 status=pending；
    4. ``send_task`` 被调用 1 次（chain dispatch 投递）；
    5. ``send_task`` 的 ``args`` 是新 render 任务的 task_id，``queue=fast``。
    """

    estimate_mock = _install_common_mocks(
        monkeypatch, word_timestamps=fake_word_timestamps
    )

    asyncio.run(_seed_video_file(patched_session))

    task_id = "task-asr-chain-into-render"
    asyncio.run(_seed_generation_task(patched_session, task_id=task_id))

    with patch(
        "app.services.commerce.task_dispatch.celery_app.send_task"
    ) as mock_send_task:
        mock_send_task.return_value = MagicMock(id="celery-mock-id")

        asyncio.run(
            run_asr_subtitle_generate_task(
                task_id,
                {
                    "video_file_id": _VIDEO_FILE_ID,
                    "shot_id": _SHOT_ID,
                    "style_id": _STYLE_ID,
                },
            )
        )

        estimate_mock.assert_awaited_once()
        mock_send_task.assert_called_once()
        broker_args, broker_kwargs = mock_send_task.call_args
        assert broker_args[0] == "task.execute"
        assert broker_kwargs["queue"] == "fast"

    async def _inspect():
        async with patched_session() as db:
            asr_row = await db.get(GenerationTask, task_id)
            assert asr_row is not None
            assert asr_row.status == GenerationTaskStatus.succeeded
            result = asr_row.result
            assert isinstance(result, dict)
            assert result["shot_id"] == _SHOT_ID, "B6: result 必须含 shot_id"
            assert result["source_file_id"] == _VIDEO_FILE_ID
            assert result["duration_ms"] == 1280
            assert isinstance(result["word_timestamps"], list)
            assert len(result["word_timestamps"]) == 3

            link_rows = (
                await db.execute(
                    select(GenerationTaskLink).where(
                        GenerationTaskLink.task_id == task_id
                    )
                )
            ).scalars().all()
            assert len(link_rows) == 1, (
                "B6: ASR 成功时应写一行 GenerationTaskLink 关联 shot_id"
            )
            link = link_rows[0]
            assert link.resource_type == "subtitle"
            assert link.relation_type == "shot"
            assert link.relation_entity_id == _SHOT_ID

            render_rows = (
                await db.execute(
                    select(GenerationTask).where(
                        GenerationTask.task_kind == "shot_subtitle_render"
                    )
                )
            ).scalars().all()
            assert len(render_rows) == 1, (
                "B3: ASR 成功后应链式派发 1 个 shot_subtitle_render 任务"
            )
            render = render_rows[0]
            assert render.status == GenerationTaskStatus.pending
            run_args = render.payload["run_args"]
            assert run_args["shot_id"] == _SHOT_ID
            assert run_args["style_id"] == _STYLE_ID
            assert run_args["source"] == "asr_paraformer_v2"
            assert isinstance(run_args["word_timestamps"], list)
            assert len(run_args["word_timestamps"]) == 3
            assert run_args["word_timestamps"][0]["text"] == "今天"

    asyncio.run(_inspect())


def test_asr_legacy_caller_without_shot_id_skips_chain_dispatch(
    patched_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    fake_word_timestamps: list[TtsWordTimestamp],
) -> None:
    """缺 ``shot_id`` 的 legacy 调用：不写 task_link，不链式派发，但 ASR 自身仍 succeeded。

    用于保证向后兼容：未升级到 W19b 写法的调用方仍然可以使用 ASR
    worker，只是不享受链式派发能力。
    """

    _install_common_mocks(monkeypatch, word_timestamps=fake_word_timestamps)

    asyncio.run(_seed_video_file(patched_session))

    task_id = "task-asr-legacy-no-shot"
    asyncio.run(_seed_generation_task(patched_session, task_id=task_id))

    with patch(
        "app.services.commerce.task_dispatch.celery_app.send_task"
    ) as mock_send_task:
        mock_send_task.return_value = MagicMock(id="celery-mock-id")

        asyncio.run(
            run_asr_subtitle_generate_task(
                task_id, {"video_file_id": _VIDEO_FILE_ID}
            )
        )

        mock_send_task.assert_not_called()

    async def _inspect():
        async with patched_session() as db:
            asr_row = await db.get(GenerationTask, task_id)
            assert asr_row is not None
            assert asr_row.status == GenerationTaskStatus.succeeded
            assert asr_row.result["shot_id"] is None, (
                "缺 shot_id 时 result.shot_id 应该是 None（向后兼容标记）"
            )

            link_rows = (
                await db.execute(
                    select(GenerationTaskLink).where(
                        GenerationTaskLink.task_id == task_id
                    )
                )
            ).scalars().all()
            assert link_rows == [], (
                "缺 shot_id 时不应写 GenerationTaskLink"
            )

            render_rows = (
                await db.execute(
                    select(GenerationTask).where(
                        GenerationTask.task_kind == "shot_subtitle_render"
                    )
                )
            ).scalars().all()
            assert render_rows == [], (
                "缺 shot_id 时不应链式派发 shot_subtitle_render"
            )

    asyncio.run(_inspect())
