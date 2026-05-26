"""TTS 合成 worker（P3 W17 T17-5）。

为什么存在
----------

P3 剧情带货链路在 W17 引入 ``tts_generate`` 任务：把镜头/对白文本送
DashScope CosyVoice WebSocket 合成为音频，并将结果（音频 + 字级时间戳）
持久化为 ``FileItem`` + ``TtsCache`` 行供下游字幕对齐与配音轨复用。

本 worker 与 :class:`DashScopeTtsApiAdapter` 形成上下层互补：

- adapter 层只关心“给定 ``ProviderConfig`` + ``TtsRequest``，怎样产出
  ``(audio_bytes, word_timestamps)``”，不接触数据库与对象存储；
- 本 worker 层负责：
  1. 解析 ``GenerationTask.payload['run_args']`` 中的
     ``text`` / ``voice_pack_id`` / ``speed`` / ``audio_format`` 等参数；
  2. 计算 :class:`TtsCacheKey` hash 命中既有 ``tts_cache`` 行 →
     直接复用 ``audio_file_id``，``hit_count`` 自增，节省供应商成本；
  3. 未命中则加载 :class:`VoicePack` 拿 ``provider_voice_id``、解析
     ``aliyun_bailian`` Provider 行的 api_key、调 adapter 合成；
  4. 合成结果 bytes 上传到对象存储并落 ``FileItem``（``FileUsageKind.tts_audio``），
     再写入 ``tts_cache`` 行；
  5. 最终把 :class:`TtsResult` 通过 ``model_dump(mode="json")`` 写入
     ``GenerationTask.result`` 并把状态推进到 ``succeeded``。

设计要点
--------

- 沿用 hotfix-4 canonical worker 模板（参考 ``product_info_extract_worker``）：
  ``async with async_session_maker()`` + ``set_status(running)`` →
  cancel check → 业务逻辑 → cancel check → ``set_result`` →
  ``set_status(succeeded)``；失败时 rollback + 独立会话写 failed。
- 默认超时 ``300s``，对齐 P3 plan 中 ``tts_generate`` 的 SLA（fast 队列
  + 5 分钟硬上限），与 ``product_info_extract`` 保持一致。
- 缓存键统一通过 :meth:`TtsCacheKey.to_hash` 计算，避免散落实现导致命中失效；
  ``speed:.3f`` 固定 3 位小数与 contracts 同源。
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.contracts.provider import ProviderConfig
from app.core.contracts.tts import (
    TtsCacheKey,
    TtsRequest,
    TtsResult,
    TtsWordTimestamp,
)
from app.core.db import async_session_maker
from app.core.integrations.aliyun.dashscope_tts import DashScopeTtsApiAdapter
from app.core.task_manager import SqlAlchemyTaskStore
from app.core.task_manager.types import TaskStatus
from app.models.llm import Provider
from app.models.studio import FileItem, FileType
from app.models.voice_pack import TtsCache, VoicePack
from app.services.llm.provider_registry import try_resolve_provider_key_from_name
from app.services.worker.async_task_support import cancel_if_requested_async
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_logging import log_task_event, log_task_failure


logger = logging.getLogger(__name__)


TASK_KIND = "tts_generate"
"""注册键：与 plan ``task_kind`` 表保持一致，避免业务侧出现拼写漂移。"""

DEFAULT_TIMEOUT_SECONDS = 300.0
"""默认超时（秒）：对齐 P3 plan 中 ``tts_generate`` 的 SLA（fast 队列）。"""

_RUNNING_PROGRESS = 10
"""进入 running 时的初始进度，与 ``product_info_extract`` 保持一致。"""

_SUCCEEDED_PROGRESS = 100
"""任务成功完成时的最终进度。"""

_DEFAULT_SPEED = 1.0
_DEFAULT_AUDIO_FORMAT = "mp3"
_DEFAULT_ENABLE_WORD_TIMESTAMPS = True

#: 不同输出格式对应的 MIME。供 minio 上传与 ``Content-Type`` 推断使用。
_FORMAT_MIME_MAP: dict[str, str] = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "pcm": "audio/pcm",
    "opus": "audio/opus",
}

#: TTS 合成产物在对象存储中的目录前缀；与 ``files.py`` 的 ``prefix`` 习惯一致。
_TTS_AUDIO_PREFIX = "tts-audio"


def _coerce_speed(value: object) -> float:
    """把 ``run_args['speed']`` 安全规范化为 float。

    存在原因：
        ``GenerationTask.payload`` 中的数值经历过 JSON 序列化，可能以 int /
        str 等形式回来；而 :class:`TtsRequest` 的 Pydantic 校验会给出
        相对模糊的报错。这里提前做一次显式转换并兜底默认值，让下游
        ``TtsCacheKey`` 的 ``speed:.3f`` 直接可用。
    """

    if value is None:
        return _DEFAULT_SPEED
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return _DEFAULT_SPEED
    return _DEFAULT_SPEED


def _coerce_str(value: object, *, default: str = "") -> str:
    """把 ``run_args`` 中的字符串字段安全规范化（去首尾空白）。"""

    if value is None:
        return default
    return str(value).strip() or default


async def _resolve_dashscope_provider_config(session: AsyncSession) -> ProviderConfig:
    """加载一条注册到 ``aliyun_bailian`` 的 Provider 行并构造 ProviderConfig。

    为什么这样实现：
        DashScope CosyVoice 与 DashScope Image/Video 共享同一套 API key；
        系统不区分专门的 “TTS 默认 model”，因此通过 Provider.name 经过
        ``try_resolve_provider_key_from_name`` 解析为 ``aliyun_bailian``
        来定位有效凭据。任何一条解析命中且 ``api_key`` 非空即可使用。

    Args:
        session: 当前 worker 的 async session（用于查询 Provider 表）。

    Returns:
        包含 DashScope api_key 的 :class:`ProviderConfig`。

    Raises:
        RuntimeError: 没有可用的 ``aliyun_bailian`` Provider（未配置 / 无 api_key）。
    """

    rows = (await session.execute(select(Provider))).scalars().all()
    for provider in rows:
        if try_resolve_provider_key_from_name(provider.name) != "aliyun_bailian":
            continue
        api_key = (provider.api_key or "").strip()
        if not api_key:
            continue
        base_url = (provider.base_url or "").strip() or None
        return ProviderConfig(
            provider="aliyun_bailian",
            api_key=api_key,
            base_url=base_url,
        )
    raise RuntimeError(
        "tts_generate requires an aliyun_bailian (DashScope) provider with non-empty api_key"
    )


async def _persist_tts_audio(
    session: AsyncSession,
    *,
    audio_bytes: bytes,
    audio_format: str,
    voice_pack_id: str,
    cache_key: str,
) -> FileItem:
    """把合成音频上传到对象存储并落一行 :class:`FileItem`。

    Args:
        session: 当前 worker 的 async session（写 ``FileItem`` 行）。
        audio_bytes: adapter 返回的二进制音频内容。
        audio_format: 输出格式（``mp3`` / ``wav`` / ``pcm`` / ``opus`` 之一）。
        voice_pack_id: 用于在对象存储 key 中标注归属，便于后续清理统计。
        cache_key: 缓存键的 sha256 hash，作为对象 key 的稳定唯一前缀，
            同一 ``(text, voice_pack_id, speed)`` 重复合成时不会出现歧义。

    Returns:
        刚刚写入的 :class:`FileItem`，``id`` 已经分配并 ``flush()`` 完成。
    """

    fmt = (audio_format or _DEFAULT_AUDIO_FORMAT).lower()
    content_type = _FORMAT_MIME_MAP.get(fmt, "application/octet-stream")
    extension = f".{fmt}" if fmt else ".bin"

    storage_key = f"{_TTS_AUDIO_PREFIX}/{voice_pack_id}/{cache_key}{extension}"
    info = await storage.upload_file(
        key=storage_key,
        data=audio_bytes,
        content_type=content_type,
        extra_args={"ACL": "public-read"},
    )

    file_id = str(uuid.uuid4())
    display_name = f"tts-{voice_pack_id}-{cache_key[:8]}"
    file_obj = FileItem(
        id=file_id,
        type=FileType.audio,
        name=display_name,
        thumbnail=info.url,
        tags=[],
        storage_key=os.fspath(storage_key),
    )
    session.add(file_obj)
    await session.flush()
    await session.refresh(file_obj)
    return file_obj


def _max_end_ms(word_timestamps: list[TtsWordTimestamp]) -> int:
    """从字级时间戳推断 duration_ms（取最大 ``end_ms``）。

    DashScope CosyVoice 不直接返回总时长；对齐字幕 / 时间轴对接习惯，
    我们以最后一个词的 ``end_ms`` 为合成时长，没有时间戳则返回 0
    （后续 W17-Subtitle 会在 ASR fallback 路径补回）。
    """

    if not word_timestamps:
        return 0
    return max(item.end_ms for item in word_timestamps)


def _build_result_from_cache(
    *,
    cache_row: TtsCache,
    audio_format: str,
) -> TtsResult:
    """命中 ``tts_cache`` 时基于行内数据组装 :class:`TtsResult`。"""

    word_timestamps = [
        TtsWordTimestamp(
            text=str(item.get("text") or ""),
            begin_ms=int(item.get("begin_ms") or 0),
            end_ms=int(item.get("end_ms") or 0),
        )
        for item in (cache_row.word_timestamps or [])
        if isinstance(item, dict) and item.get("text")
    ]
    return TtsResult(
        audio_file_id=cache_row.audio_file_id,
        audio_format=audio_format,
        duration_ms=int(cache_row.duration_ms or 0),
        word_timestamps=word_timestamps,
        provider_request_id=None,
        cache_hit=True,
    )


async def _handle_cache_hit(
    *,
    session: AsyncSession,
    store: SqlAlchemyTaskStore,
    task_id: str,
    cache_row: TtsCache,
    audio_format: str,
) -> None:
    """命中缓存：自增 ``hit_count``、写 ``TtsResult(cache_hit=True)``、置 succeeded。"""

    cache_row.hit_count = int(cache_row.hit_count or 0) + 1
    result = _build_result_from_cache(cache_row=cache_row, audio_format=audio_format)
    await store.set_result(task_id, result.model_dump(mode="json"))
    await store.set_progress(task_id, _SUCCEEDED_PROGRESS)
    await store.set_status(task_id, TaskStatus.succeeded)
    await session.commit()
    log_task_event(TASK_KIND, task_id, "succeeded", cache_hit=True)


async def run_tts_generate_task(
    task_id: str,
    run_args: dict[str, Any],
) -> None:
    """异步 runner：合成 TTS 音频并把结果写回任务存储。

    输入 (``run_args``):
        - ``text`` (str, required): 待合成文本。
        - ``voice_pack_id`` (str, required): :class:`VoicePack` 主键。
        - ``speed`` (float, optional, default ``1.0``): 0.5-2.0，
          由 :class:`TtsRequest` 的 Pydantic 校验兜底。
        - ``audio_format`` (str, optional, default ``mp3``):
          ``mp3`` / ``wav`` / ``pcm`` / ``opus``。
        - ``enable_word_timestamps`` (bool, optional, default ``True``)。

    输出（写入 ``store.set_result`` 的 dict）:
        :meth:`TtsResult.model_dump` ``mode="json"``，
        包含 ``audio_file_id`` / ``duration_ms`` / ``word_timestamps`` /
        ``cache_hit`` 等字段。

    异常处理：
        与 ``product_info_extract_worker`` 一致：try 中 rollback、
        独立会话写 failed、再向上抛由 ``AbstractAsyncDelegatingExecutor``
        转换为 Celery 失败状态。
    """

    text = _coerce_str(run_args.get("text"))
    voice_pack_id = _coerce_str(run_args.get("voice_pack_id"))
    if not text:
        raise ValueError("tts_generate requires non-empty text in run_args")
    if not voice_pack_id:
        raise ValueError("tts_generate requires voice_pack_id in run_args")

    speed = _coerce_speed(run_args.get("speed"))
    audio_format = _coerce_str(
        run_args.get("audio_format"), default=_DEFAULT_AUDIO_FORMAT
    ).lower()
    enable_word_timestamps = bool(
        run_args.get("enable_word_timestamps", _DEFAULT_ENABLE_WORD_TIMESTAMPS)
    )

    cache_key = TtsCacheKey(
        text=text, voice_pack_id=voice_pack_id, speed=speed
    ).to_hash()

    async with async_session_maker() as session:
        try:
            store = SqlAlchemyTaskStore(session)
            await store.set_status(task_id, TaskStatus.running)
            await store.set_progress(task_id, _RUNNING_PROGRESS)
            await session.commit()
            log_task_event(TASK_KIND, task_id, "running")

            if await cancel_if_requested_async(
                store=store, task_id=task_id, session=session
            ):
                log_task_event(TASK_KIND, task_id, "cancelled", stage="before_execute")
                return

            # 1) cache 命中走快速分支：不调供应商、不动对象存储。
            cache_row = (
                await session.execute(
                    select(TtsCache).where(TtsCache.cache_key == cache_key)
                )
            ).scalars().first()
            if cache_row is not None:
                await _handle_cache_hit(
                    session=session,
                    store=store,
                    task_id=task_id,
                    cache_row=cache_row,
                    audio_format=audio_format,
                )
                return

            # 2) cache miss：加载 VoicePack 拿 provider_voice_id。
            voice_pack = await session.get(VoicePack, voice_pack_id)
            if voice_pack is None:
                raise LookupError(
                    f"voice_pack not found: voice_pack_id={voice_pack_id}"
                )

            provider_cfg = await _resolve_dashscope_provider_config(session)
            tts_request = TtsRequest(
                text=text,
                voice_pack_id=voice_pack_id,
                provider_voice_id=voice_pack.provider_voice_id,
                speed=speed,
                audio_format=audio_format,
                enable_word_timestamps=enable_word_timestamps,
            )

            adapter = DashScopeTtsApiAdapter()
            audio_bytes, word_timestamps = await adapter.synthesize(
                cfg=provider_cfg,
                input_=tts_request,
                timeout_s=DEFAULT_TIMEOUT_SECONDS,
            )

            if await cancel_if_requested_async(
                store=store, task_id=task_id, session=session
            ):
                log_task_event(TASK_KIND, task_id, "cancelled", stage="after_execute")
                return

            # 3) 落音频 FileItem + tts_cache 行。
            file_obj = await _persist_tts_audio(
                session,
                audio_bytes=audio_bytes,
                audio_format=audio_format,
                voice_pack_id=voice_pack_id,
                cache_key=cache_key,
            )

            duration_ms = _max_end_ms(word_timestamps)
            new_cache = TtsCache(
                cache_key=cache_key,
                voice_pack_id=voice_pack_id,
                text_preview=text[:255],
                speed=speed,
                audio_file_id=file_obj.id,
                duration_ms=duration_ms,
                word_timestamps=[ts.model_dump() for ts in word_timestamps],
                hit_count=0,
            )
            session.add(new_cache)
            await session.flush()

            result = TtsResult(
                audio_file_id=file_obj.id,
                audio_format=audio_format,
                duration_ms=duration_ms,
                word_timestamps=word_timestamps,
                provider_request_id=None,
                cache_hit=False,
            )
            await store.set_result(task_id, result.model_dump(mode="json"))
            await store.set_progress(task_id, _SUCCEEDED_PROGRESS)
            await store.set_status(task_id, TaskStatus.succeeded)
            await session.commit()
            log_task_event(TASK_KIND, task_id, "succeeded", cache_hit=False)
        except Exception as exc:  # noqa: BLE001 - 与既有 worker 模板保持一致
            await session.rollback()
            async with async_session_maker() as failure_session:
                fail_store = SqlAlchemyTaskStore(failure_session)
                await fail_store.set_error(task_id, str(exc))
                await fail_store.set_status(task_id, TaskStatus.failed)
                await failure_session.commit()
            log_task_failure(TASK_KIND, task_id, str(exc))
            raise


# ---------------------------------------------------------------------------
# Executor 工厂（供 ``task_executor_registry`` 注册使用）
# ---------------------------------------------------------------------------


def build_tts_generate_executor() -> AbstractAsyncDelegatingExecutor:
    """构造与 ``task_executor_registry`` 兼容的 TTS 执行器实例。

    存在原因：
        把构造逻辑收敛到工厂函数，便于 ``task_registry.py`` 一行
        ``register(...)`` 完成接入；同时让单测能直接断言
        ``task_kind`` 与 ``timeout_seconds`` 等默认值，
        而无需依赖全局注册表的副作用。

    Returns:
        预配置的 :class:`AbstractAsyncDelegatingExecutor`，其
        ``task_kind`` 为 :data:`TASK_KIND`，
        ``timeout_seconds`` 为 :data:`DEFAULT_TIMEOUT_SECONDS`。
    """

    return AbstractAsyncDelegatingExecutor(
        task_kind=TASK_KIND,
        runner=run_tts_generate_task,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
    )


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "TASK_KIND",
    "build_tts_generate_executor",
    "run_tts_generate_task",
]
