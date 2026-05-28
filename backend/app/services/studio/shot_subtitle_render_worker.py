"""字幕渲染 worker（P3 W18 T18-5/T18-6 + 句子切分集成）。

为什么存在：
    把 W17 收尾产出的字级时间戳（来自 TTS CosyVoice synthesize 或 keep_native
    路径的 Paraformer-v2 ASR 反推）渲染成 ``.ass`` 字幕文件，落 minio +
    SubtitleTrack 表，供下游 chapter_av_export（W19）做 hardsub 烧录。

    本 worker 是 W18 字幕引擎的执行层入口，与 ``tts_generate_worker`` /
    ``asr_subtitle_generate_worker`` 并列在 ``fast`` 队列。

做什么：
    异步 runner 输入 ``run_args``：

    - ``shot_id`` (str, required): 字幕所属镜头 ID（用于落 SubtitleTrack.shot_id）。
    - ``style_id`` (str, required): 使用的 SubtitleStyle ID（DOUYIN_DEFAULT
      等系统级或项目级覆盖）。worker 通过
      :func:`app.services.studio.subtitle_style_service.resolve_for_shot`
      做"项目级 → 系统级 fallback"两级解析，确保用户中途修改项目覆盖
      立即生效。
    - ``word_timestamps`` (list[dict], required): 字级时间戳数组，元素含
      ``text`` / ``begin_ms`` / ``end_ms`` 三字段；上游可能是 ``TtsResult.word_timestamps``
      或 ``asr_subtitle_generate`` 任务结果中的同名字段。
    - ``language_code`` (str, optional, default ``zh-CN``): 决定句子切分模式与
      SubtitleTrack.language_code。
    - ``source`` (str, optional, default ``tts_word_timestamps``): SubtitleSource
      枚举字符串，标记字级时间戳来源（与 W17 收尾 audio_strategy 双路径对齐）。

    输出（写入 ``store.set_result``）：

    - ``subtitle_track_id``: 新建 SubtitleTrack 行 ID。
    - ``file_id``: 渲染产物 .ass FileItem ID。
    - ``style_id``: echo 输入。
    - ``language_code``: echo 输入。
    - ``source``: echo 输入。
    - ``cue_count``: 切分后的 cue 数量。
    - ``duration_ms``: 字幕末尾时间戳。
    - ``warnings``: 安全区 lint 告警列表（不阻塞渲染，仅供前端展示）。

设计要点：

- 完整复用 hotfix-4 canonical 模板（参考 ``tts_generate_worker``）：
  ``async with async_session_maker()`` + ``set_status(running)`` →
  cancel check → 业务 → cancel check → ``set_result`` →
  ``set_status(succeeded)``；失败时 rollback + 独立会话写 failed。
- 默认超时 ``120s``：纯计算 + 一次 minio 上传，比 TTS / ASR 快得多。
- ``fast`` 队列：与 TTS / ASR 对齐，避免与视频 / 章节合成 worker 抢占。
- 渲染逻辑全部在 ``subtitle_renderer`` 纯函数模块，本文件只做编排：
  解析 run_args → :func:`subtitle_style_service.resolve_for_shot` 做项目级
  优先 / 系统级 fallback 两级 lookup → 切分 cue → 渲染 ASS →
  上传 minio → 落 SubtitleTrack。
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.db import async_session_maker
from app.core.task_manager import SqlAlchemyTaskStore
from app.core.task_manager.types import TaskStatus
from app.models.studio import FileItem, FileType
from app.models.subtitle import SubtitleTrack
from app.models.types import SubtitleSource
from app.services.studio.subtitle_renderer import (
    render_ass,
    split_words_into_cues,
)
from app.services.studio.subtitle_safe_zone import check_safe_zone
from app.services.studio.subtitle_style_service import resolve_for_shot
from app.services.worker.async_task_support import cancel_if_requested_async
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_logging import log_task_event, log_task_failure


logger = logging.getLogger(__name__)


TASK_KIND = "shot_subtitle_render"
"""注册键：与 plan ``task_kind`` 表保持一致，避免业务侧出现拼写漂移。"""

DEFAULT_TIMEOUT_SECONDS = 120.0
"""默认超时（秒）：纯计算 + 一次 minio 上传，120s 已是宽裕上限。"""

_RUNNING_PROGRESS = 10
"""进入 running 时的初始进度，与 ``tts_generate_worker`` 保持一致。"""

_SUCCEEDED_PROGRESS = 100
"""任务成功完成时的最终进度。"""

_DEFAULT_LANGUAGE_CODE = "zh-CN"
_DEFAULT_SOURCE = SubtitleSource.tts_word_timestamps

#: 字幕产物在对象存储中的目录前缀；与 ``files.py`` 的 ``prefix`` 习惯一致。
_SUBTITLE_PREFIX = "subtitles"


def _coerce_str(value: object, *, default: str = "") -> str:
    """把 ``run_args`` 中的字符串字段安全规范化（去首尾空白）。"""

    if value is None:
        return default
    return str(value).strip() or default


def _coerce_word_timestamps(value: object) -> list[dict[str, Any]]:
    """把 ``run_args['word_timestamps']`` 兜底为 ``list[dict]``。

    ``GenerationTask.payload`` 的 JSON 反序列化可能给出 ``None`` /
    单字典 / dict 列表三种形态；统一返回 list[dict]，让 ``subtitle_renderer``
    内部做更细的 ``text`` / ``begin_ms`` / ``end_ms`` 兜底。
    """

    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _coerce_source(value: object) -> SubtitleSource:
    """把 ``run_args['source']`` 兜底为 :class:`SubtitleSource` 枚举。

    缺省 / 不可识别值 → ``tts_word_timestamps``，与 silent_with_tts 主路径一致。
    """

    if isinstance(value, SubtitleSource):
        return value
    raw = _coerce_str(value)
    if not raw:
        return _DEFAULT_SOURCE
    try:
        return SubtitleSource(raw)
    except ValueError:
        return _DEFAULT_SOURCE


async def _persist_subtitle_file(
    session: AsyncSession,
    *,
    ass_text: str,
    shot_id: str,
    style_id: str,
) -> FileItem:
    """把渲染好的 ``.ass`` 文本上传到对象存储并落一行 :class:`FileItem`。

    Args:
        session: 当前 worker 的 async session（写 ``FileItem`` 行）。
        ass_text: ``render_ass()`` 输出的完整 .ass 文件文本。
        shot_id: 字幕所属镜头 ID，用于对象存储 key 路径分组。
        style_id: 使用的 SubtitleStyle ID，用于对象存储 key 子目录区分。

    Returns:
        刚刚写入的 :class:`FileItem`，``id`` 已经分配并 ``flush()`` 完成。
    """

    file_id = str(uuid.uuid4())
    storage_key = f"{_SUBTITLE_PREFIX}/{shot_id}/{style_id}/{file_id}.ass"
    info = await storage.upload_file(
        key=storage_key,
        data=ass_text.encode("utf-8"),
        content_type="text/x-ssa",
        extra_args={"ACL": "public-read"},
    )

    display_name = f"subtitle-{shot_id}-{style_id[:16]}"
    # FileType 枚举目前只有 image / video / audio；ASS 字幕属于 "下游音轨配套
    # 元数据"，性质最接近 audio（描述音频时间线），先复用 audio。后续若引入
    # FileType.subtitle 需联动 W18 后续 wave 修订。
    file_obj = FileItem(
        id=file_id,
        type=FileType.audio,
        name=display_name,
        thumbnail=info.url,
        tags=["subtitle", "ass"],
        storage_key=os.fspath(storage_key),
    )
    session.add(file_obj)
    await session.flush()
    await session.refresh(file_obj)
    return file_obj


async def run_shot_subtitle_render_task(
    task_id: str,
    run_args: dict[str, Any],
) -> None:
    """异步 runner：渲染字幕 ASS 并落 SubtitleTrack。

    异常处理：
        与 ``tts_generate_worker`` 一致：try 中 rollback、独立会话写 failed、
        再向上抛由 ``AbstractAsyncDelegatingExecutor`` 转换为 Celery 失败状态。
    """

    shot_id = _coerce_str(run_args.get("shot_id"))
    style_id = _coerce_str(run_args.get("style_id"))
    if not shot_id:
        raise ValueError(
            "shot_subtitle_render requires non-empty shot_id in run_args"
        )
    if not style_id:
        raise ValueError(
            "shot_subtitle_render requires non-empty style_id in run_args"
        )

    word_timestamps = _coerce_word_timestamps(run_args.get("word_timestamps"))
    language_code = _coerce_str(
        run_args.get("language_code"), default=_DEFAULT_LANGUAGE_CODE
    )
    source = _coerce_source(run_args.get("source"))

    async with async_session_maker() as session:
        try:
            store = SqlAlchemyTaskStore(session)
            await store.set_status(task_id, TaskStatus.running)
            await store.set_progress(task_id, _RUNNING_PROGRESS)
            await session.commit()
            log_task_event(TASK_KIND, task_id, "running", shot_id=shot_id)

            if await cancel_if_requested_async(
                store=store, task_id=task_id, session=session
            ):
                log_task_event(TASK_KIND, task_id, "cancelled", stage="before_execute")
                return

            style = await resolve_for_shot(
                db=session,
                shot_id=shot_id,
                style_id_hint=style_id,
            )

            warnings = check_safe_zone(style)

            cues = split_words_into_cues(
                word_timestamps,
                language_code=language_code,
            )
            ass_text = render_ass(style, cues)

            if await cancel_if_requested_async(
                store=store, task_id=task_id, session=session
            ):
                log_task_event(TASK_KIND, task_id, "cancelled", stage="after_execute")
                return

            file_obj = await _persist_subtitle_file(
                session,
                ass_text=ass_text,
                shot_id=shot_id,
                style_id=style.id,
            )

            duration_ms = cues[-1].end_ms if cues else 0
            track_id = uuid.uuid4().hex
            track = SubtitleTrack(
                id=track_id,
                shot_id=shot_id,
                style_id=style.id,
                file_id=file_obj.id,
                language_code=language_code,
                format=style.format,
                source=source,
                duration_ms=duration_ms,
            )
            session.add(track)
            await session.flush()

            payload: dict[str, Any] = {
                "subtitle_track_id": track_id,
                "file_id": file_obj.id,
                "style_id": style.id,
                "language_code": language_code,
                "source": source.value,
                "cue_count": len(cues),
                "duration_ms": duration_ms,
                "warnings": warnings,
            }
            await store.set_result(task_id, payload)
            await store.set_progress(task_id, _SUCCEEDED_PROGRESS)
            await store.set_status(task_id, TaskStatus.succeeded)
            await session.commit()
            log_task_event(
                TASK_KIND,
                task_id,
                "succeeded",
                shot_id=shot_id,
                cue_count=len(cues),
                duration_ms=duration_ms,
                warning_count=len(warnings),
            )
        except Exception as exc:  # noqa: BLE001 - 与既有 worker 模板保持一致
            await session.rollback()
            async with async_session_maker() as failure_session:
                fail_store = SqlAlchemyTaskStore(failure_session)
                await fail_store.set_error(task_id, str(exc))
                await fail_store.set_status(task_id, TaskStatus.failed)
                await failure_session.commit()
            log_task_failure(TASK_KIND, task_id, str(exc))
            raise


def build_shot_subtitle_render_executor() -> AbstractAsyncDelegatingExecutor:
    """构造与 ``task_executor_registry`` 兼容的字幕渲染执行器实例。

    存在原因：
        把构造逻辑收敛到工厂函数，便于 ``task_registry.py`` 一行
        ``register(...)`` 完成接入；同时让单测能直接断言 ``task_kind``
        与 ``timeout_seconds`` 等默认值，而无需依赖全局注册表的副作用。

    Returns:
        预配置的 :class:`AbstractAsyncDelegatingExecutor`，其
        ``task_kind`` 为 :data:`TASK_KIND`，
        ``timeout_seconds`` 为 :data:`DEFAULT_TIMEOUT_SECONDS`。
    """

    return AbstractAsyncDelegatingExecutor(
        task_kind=TASK_KIND,
        runner=run_shot_subtitle_render_task,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
    )


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "TASK_KIND",
    "build_shot_subtitle_render_executor",
    "run_shot_subtitle_render_task",
]
