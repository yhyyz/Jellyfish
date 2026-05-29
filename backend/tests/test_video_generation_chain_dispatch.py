"""``run_video_generation_task`` chain dispatch 集成测试（P3 W19）。

验证 W19 video 成功路径自动派发：

1. ``run_args.meta.audio_strategy == "silent_with_tts"`` →  遍历 ShotDialogLine
   逐行派发 ``tts_generate``；
2. ``run_args.meta.audio_strategy == "keep_native"`` → 派发 1 个
   ``asr_subtitle_generate`` 指向刚生成的视频 FileItem；
3. 缺失 ``meta.audio_strategy`` → 不派发任何子任务（向后兼容）；
4. ``silent_with_tts`` 但对白行无 ``tts_voice_id`` → skip（不阻塞主链路）；
5. video 失败 → 不派发任何子任务（chain dispatch 仅在成功路径执行）。

测试架构：mock VideoGenerationTask + persist_generated_video_to_shot +
recompute_shot_status 以隔离主链路；observable 仅断言 GenerationTask 行的
新增情况（chain dispatch 派发的子任务）。
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

from app.core.contracts.video_generation import VideoGenerationResult
from app.core.db import Base
from app.models.studio import (
    Chapter,
    FileItem,
    FileType,
    Project,
    ProjectStyle,
    Shot,
    ShotDetail,
    ShotDialogLine,
    ShotStatus,
)
from app.models.studio_shots import DialogueLineMode
from app.models.studio_shots import (
    CameraAngle,
    CameraMovement,
    CameraShotType,
)
from app.models.subtitle import SubtitleStyle
from app.models.task import GenerationDeliveryMode, GenerationTask, GenerationTaskStatus
from app.models.types import AudioStrategy, SubtitleAlignment, SubtitleFormat
from app.models.voice_pack import VoicePack
from app.models.types import VoiceGender, VoiceProvider
from app.services.film import generated_video as gen_mod
from app.services.film.generated_video import run_video_generation_task


_PROJECT_ID = "proj-w19-chain"
_CHAPTER_ID = "chap-w19-chain"
_SHOT_ID = "shot-w19-chain"
_VOICE_PACK_ID = "cosyvoice_v2_test_chain"


@pytest.fixture
def session_local(tmp_path) -> Generator[async_sessionmaker[AsyncSession], None, None]:
    """文件型 SQLite + Base.metadata.create_all。"""

    db_path = tmp_path / "video-chain-dispatch.db"
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
def patched(
    session_local: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> async_sessionmaker[AsyncSession]:
    """统一 patch worker 模块 + Celery send_task + 业务依赖。"""

    monkeypatch.setattr(gen_mod, "async_session_maker", session_local)

    async def _never_cancel(*_: Any, **__: Any) -> bool:
        return False

    monkeypatch.setattr(gen_mod, "cancel_if_requested_async", _never_cancel)

    async def _fake_recompute(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(gen_mod, "recompute_shot_status", _fake_recompute)

    return session_local


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_full_project(
    sm: async_sessionmaker[AsyncSession],
    *,
    dialog_lines: list[tuple[str, str | None]] | None = None,
    seed_subtitle_style: bool = True,
) -> None:
    """种入 Project / Chapter / Shot / ShotDetail / VoicePack（可选）/ ShotDialogLine。

    ``dialog_lines`` 为 ``[(text, voice_pack_id_or_None), ...]``：voice_pack_id
    为 None 时不绑定音色（用于测试 skip 分支）。

    ``seed_subtitle_style`` 默认 ``True``：keep_native 路径会在 chain dispatch
    时调用 ``_resolve_default_subtitle_style_id``，缺这条 SubtitleStyle 会
    抛 RuntimeError。silent_with_tts 不依赖该样式，但补一行也无副作用。
    """

    async with sm() as db:
        db.add(
            Project(
                id=_PROJECT_ID,
                name="W19 chain test",
                style=ProjectStyle.real_people_city,
            )
        )
        db.add(
            Chapter(
                id=_CHAPTER_ID,
                project_id=_PROJECT_ID,
                index=1,
                title="测试章",
            )
        )
        db.add(
            Shot(
                id=_SHOT_ID,
                chapter_id=_CHAPTER_ID,
                index=1,
                title="测试镜头",
                status=ShotStatus.ready,
            )
        )
        db.add(
            ShotDetail(
                id=_SHOT_ID,
                camera_shot=CameraShotType.ms,
                angle=CameraAngle.eye_level,
                movement=CameraMovement.static,
                duration=5,
            )
        )
        db.add(
            VoicePack(
                id=_VOICE_PACK_ID,
                name="测试音色",
                provider=VoiceProvider.aliyun_cosyvoice,
                provider_voice_id="longxiaochun_v2",
                language_code="zh-CN",
                gender=VoiceGender.female,
                description="chain test",
                default_speed=1.0,
                is_system=True,
                sort_order=0,
            )
        )

        for idx, (text, voice_pack_id) in enumerate(dialog_lines or []):
            db.add(
                ShotDialogLine(
                    shot_detail_id=_SHOT_ID,
                    index=idx,
                    text=text,
                    line_mode=DialogueLineMode.dialogue,
                    tts_voice_id=voice_pack_id,
                    start_time_ms=idx * 1000,
                    end_time_ms=(idx + 1) * 1000,
                )
            )

        if seed_subtitle_style:
            db.add(
                SubtitleStyle(
                    id="douyin_default",
                    name="抖音默认",
                    description="测试用默认字幕样式",
                    language_code="zh-CN",
                    format=SubtitleFormat.ass,
                    font_family="Source Han Sans CN Heavy",
                    font_fallback_chain=["Source Han Sans CN Heavy", "Arial"],
                    font_size=72,
                    primary_colour="&H00FFFFFF",
                    secondary_colour="&H00FFFFFF",
                    outline_colour="&H00000000",
                    back_colour="&H80000000",
                    bold=True,
                    italic=False,
                    border_style=1,
                    outline=3.0,
                    shadow=1.0,
                    alignment=SubtitleAlignment.bottom_center,
                    margin_l=60,
                    margin_r=60,
                    margin_v=200,
                    play_res_x=1080,
                    play_res_y=1920,
                    is_system=True,
                    sort_order=0,
                )
            )

        await db.commit()


async def _seed_video_generation_task(
    sm: async_sessionmaker[AsyncSession],
    *,
    task_id: str,
    audio_strategy: str | None,
) -> None:
    """种一行 ``video_generation`` 任务行；run_args.meta.audio_strategy 由参数控制。"""

    run_args: dict[str, Any] = {
        "shot_id": _SHOT_ID,
        "provider": "aliyun_bailian",
        "api_key": "sk-test",
        "input": {
            "prompt": "test",
            "model": "happyhorse-1.0-t2v",
            "ratio": "16:9",
            "seconds": 5,
        },
    }
    if audio_strategy is not None:
        run_args["meta"] = {"audio_strategy": audio_strategy}

    async with sm() as db:
        db.add(
            GenerationTask(
                id=task_id,
                mode=GenerationDeliveryMode.async_polling,
                task_kind="video_generation",
                status=GenerationTaskStatus.pending,
                progress=0,
                payload={"task_kind": "video_generation", "run_args": run_args},
                result=None,
                error="",
            )
        )
        await db.commit()


def _install_video_pipeline_mocks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fake_file_id: str = "file-w19-video",
    raise_at_video_run: Exception | None = None,
) -> MagicMock:
    """Mock VideoGenerationTask + persist_generated_video_to_shot。

    返回的 MagicMock 是 send_task 的 mock，便于断言子任务投递次数。
    ``raise_at_video_run`` 非 None 时在 ``task.run()`` 抛错（测试失败路径）。
    """

    fake_result = VideoGenerationResult(
        url="https://cdn.example.com/fake.mp4",
        provider_task_id="req-fake",
    )

    class _FakeVideoTask:
        def __init__(self, **_: Any) -> None:
            pass

        async def run(self) -> None:
            if raise_at_video_run is not None:
                raise raise_at_video_run

        async def get_result(self) -> VideoGenerationResult:
            return fake_result

        async def status(self) -> dict[str, Any]:
            return {}

    monkeypatch.setattr(gen_mod, "VideoGenerationTask", _FakeVideoTask)

    async def _fake_persist(session: AsyncSession, *_: Any, **__: Any) -> FileItem:
        file_obj = FileItem(
            id=fake_file_id,
            type=FileType.video,
            name="fake-video",
            thumbnail="https://cdn.example.com/fake.mp4",
            tags=[],
            storage_key=f"generated-videos/{fake_file_id}.mp4",
        )
        session.add(file_obj)
        await session.flush()
        return file_obj

    monkeypatch.setattr(gen_mod, "persist_generated_video_to_shot", _fake_persist)

    send_task_mock = MagicMock(return_value=MagicMock(id="celery-stub"))
    monkeypatch.setattr(
        "app.services.commerce.task_dispatch.celery_app.send_task",
        send_task_mock,
    )
    return send_task_mock


# ---------------------------------------------------------------------------
# 1. silent_with_tts → 派发 N 个 tts_generate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_silent_with_tts_dispatches_one_tts_per_dialog_line(
    patched: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """silent_with_tts：每条带 voice_pack 的对白行派发 1 个 tts_generate。"""

    send_task = _install_video_pipeline_mocks(monkeypatch)
    await _seed_full_project(
        patched,
        dialog_lines=[
            ("第一句对白", _VOICE_PACK_ID),
            ("第二句对白", _VOICE_PACK_ID),
            ("第三句对白", _VOICE_PACK_ID),
        ],
    )
    task_id = "task-w19-silent"
    await _seed_video_generation_task(
        patched, task_id=task_id, audio_strategy="silent_with_tts"
    )

    await run_video_generation_task(
        task_id,
        {
            "shot_id": _SHOT_ID,
            "provider": "aliyun_bailian",
            "api_key": "sk-test",
            "input": {"prompt": "test", "model": "happyhorse-1.0-t2v", "ratio": "16:9", "seconds": 5},
            "meta": {"audio_strategy": AudioStrategy.silent_with_tts.value},
        },
    )

    async with patched() as db:
        # 主任务成功。
        main_task = await db.get(GenerationTask, task_id)
        assert main_task is not None
        assert main_task.status == GenerationTaskStatus.succeeded

        # 3 条 tts_generate 子任务行已落库（每条对白一行）。
        rows = (
            await db.execute(
                select(GenerationTask).where(
                    GenerationTask.task_kind == "tts_generate"
                )
            )
        ).scalars().all()
        assert len(rows) == 3
        for row in rows:
            assert row.payload["task_kind"] == "tts_generate"
            assert row.payload["run_args"]["voice_pack_id"] == _VOICE_PACK_ID
            assert row.status == GenerationTaskStatus.pending

    # send_task 被调用 4 次：3 tts_generate + 1 shot_consistency_check
    # （P4 W27-T2 给 video 成功路径加的无条件链式派发，与 audio_strategy 无关）。
    assert send_task.call_count == 4


# ---------------------------------------------------------------------------
# 2. keep_native → 派发 1 个 asr_subtitle_generate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_keep_native_dispatches_single_asr_subtitle_generate(
    patched: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """keep_native：派发 1 个 asr_subtitle_generate 指向刚生成的视频 FileItem。"""

    fake_file_id = "file-w19-keepnative"
    send_task = _install_video_pipeline_mocks(monkeypatch, fake_file_id=fake_file_id)
    # keep_native 路径不依赖对白行（直接对视频反推），种 0 行也应正常派发。
    await _seed_full_project(patched, dialog_lines=[])

    task_id = "task-w19-native"
    await _seed_video_generation_task(
        patched, task_id=task_id, audio_strategy="keep_native"
    )

    await run_video_generation_task(
        task_id,
        {
            "shot_id": _SHOT_ID,
            "provider": "aliyun_bailian",
            "api_key": "sk-test",
            "input": {"prompt": "test", "model": "happyhorse-1.0-t2v", "ratio": "16:9", "seconds": 5},
            "meta": {"audio_strategy": AudioStrategy.keep_native.value},
        },
    )

    async with patched() as db:
        rows = (
            await db.execute(
                select(GenerationTask).where(
                    GenerationTask.task_kind == "asr_subtitle_generate"
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        run_args = rows[0].payload["run_args"]
        assert run_args["video_file_id"] == fake_file_id
        assert run_args["shot_id"] == _SHOT_ID, (
            "B3：keep_native chain dispatch 必须把 shot_id 写进 ASR run_args"
        )
        assert run_args["style_id"] == "douyin_default", (
            "B3：keep_native chain dispatch 必须把默认 style_id 写进 ASR run_args"
        )

    # send_task 被调用 2 次：1 asr_subtitle_generate + 1 shot_consistency_check (W27-T2)。
    assert send_task.call_count == 2


# ---------------------------------------------------------------------------
# 3. 无 audio_strategy → 不派发（向后兼容）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_audio_strategy_means_no_chain_dispatch(
    patched: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_args.meta 缺失 audio_strategy（W17 收尾前的老调用方）→ 不派发任何子任务。"""

    send_task = _install_video_pipeline_mocks(monkeypatch)
    await _seed_full_project(
        patched,
        dialog_lines=[("对白1", _VOICE_PACK_ID), ("对白2", _VOICE_PACK_ID)],
    )

    task_id = "task-w19-no-meta"
    await _seed_video_generation_task(
        patched, task_id=task_id, audio_strategy=None
    )

    await run_video_generation_task(
        task_id,
        {
            "shot_id": _SHOT_ID,
            "provider": "aliyun_bailian",
            "api_key": "sk-test",
            "input": {"prompt": "test", "model": "happyhorse-1.0-t2v", "ratio": "16:9", "seconds": 5},
            # 故意不带 meta 字段。
        },
    )

    async with patched() as db:
        rows = (
            await db.execute(
                select(GenerationTask).where(
                    GenerationTask.task_kind.in_(
                        ("tts_generate", "asr_subtitle_generate")
                    )
                )
            )
        ).scalars().all()
        assert rows == []

    # send_task 被调用 1 次：仅 W27-T2 给 video 成功路径加的无条件
    # shot_consistency_check 链式派发；audio_strategy 缺失意味着不派发
    # tts/asr 子任务，但 consistency check 与 audio 无关，仍会派发。
    assert send_task.call_count == 1


# ---------------------------------------------------------------------------
# 4. silent_with_tts 但缺 voice_id → skip 不阻塞
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_silent_with_tts_skips_lines_missing_voice_id(
    patched: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """silent_with_tts 路径：缺 voice_id 或空文本的对白行 skip 不阻塞主链路。"""

    send_task = _install_video_pipeline_mocks(monkeypatch)
    await _seed_full_project(
        patched,
        dialog_lines=[
            ("有效对白", _VOICE_PACK_ID),
            ("缺 voice_id 应被 skip", None),
            ("第三条带 voice", _VOICE_PACK_ID),
        ],
    )

    task_id = "task-w19-skip"
    await _seed_video_generation_task(
        patched, task_id=task_id, audio_strategy="silent_with_tts"
    )

    await run_video_generation_task(
        task_id,
        {
            "shot_id": _SHOT_ID,
            "provider": "aliyun_bailian",
            "api_key": "sk-test",
            "input": {"prompt": "test", "model": "happyhorse-1.0-t2v", "ratio": "16:9", "seconds": 5},
            "meta": {"audio_strategy": "silent_with_tts"},
        },
    )

    async with patched() as db:
        # 主任务仍然成功（skip 不阻塞）。
        main_task = await db.get(GenerationTask, task_id)
        assert main_task is not None
        assert main_task.status == GenerationTaskStatus.succeeded

        # 仅 2 条 tts_generate 派发（第二条缺 voice_id 被 skip）。
        rows = (
            await db.execute(
                select(GenerationTask).where(
                    GenerationTask.task_kind == "tts_generate"
                )
            )
        ).scalars().all()
        assert len(rows) == 2

    # send_task 被调用 3 次：2 tts_generate (1 行因缺 voice_id 被 skip) +
    # 1 shot_consistency_check (W27-T2 无条件链式派发)。
    assert send_task.call_count == 3


# ---------------------------------------------------------------------------
# 5. video 失败 → 不派发（chain dispatch 仅在成功路径执行）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_video_failure_does_not_trigger_chain_dispatch(
    patched: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """video 任务失败时，chain dispatch 不应执行（运行在成功分支之后）。"""

    send_task = _install_video_pipeline_mocks(
        monkeypatch, raise_at_video_run=RuntimeError("video pipeline boom")
    )
    await _seed_full_project(
        patched, dialog_lines=[("对白", _VOICE_PACK_ID)]
    )

    task_id = "task-w19-fail"
    await _seed_video_generation_task(
        patched, task_id=task_id, audio_strategy="silent_with_tts"
    )

    # video_generation worker 失败时本身不再 raise（hotfix-4 模板），
    # 仅把 GenerationTask.status 置为 failed。
    await run_video_generation_task(
        task_id,
        {
            "shot_id": _SHOT_ID,
            "provider": "aliyun_bailian",
            "api_key": "sk-test",
            "input": {"prompt": "test", "model": "happyhorse-1.0-t2v", "ratio": "16:9", "seconds": 5},
            "meta": {"audio_strategy": "silent_with_tts"},
        },
    )

    async with patched() as db:
        main_task = await db.get(GenerationTask, task_id)
        assert main_task is not None
        assert main_task.status == GenerationTaskStatus.failed

        rows = (
            await db.execute(
                select(GenerationTask).where(
                    GenerationTask.task_kind.in_(
                        ("tts_generate", "asr_subtitle_generate")
                    )
                )
            )
        ).scalars().all()
        assert rows == []

    assert send_task.call_count == 0
