"""ASR 字幕反推 worker（P3 W17 收尾，Decision D 修订）。

为什么存在
----------

P3 剧情带货链路在 W17 引入两条音轨路径：

- ``silent_with_tts``（默认）：丢弃模型自带音轨，由 ``tts_generate`` 合成 TTS
  音频覆盖，``word_timestamps`` 来自 CosyVoice synthesize；
- ``keep_native``（W17 收尾启用，Decision D 修订的逃生口）：保留视频生成
  模型自带原音，把 ASR 反推得到的字级时间戳作为字幕来源，配合保留口型场景。

本 worker 服务 ``keep_native`` 路径：把已落库的 video / audio FileItem
对应的对象存储 public URL 送进 DashScope Paraformer-v2 异步 ASR，拿到
``list[TtsWordTimestamp]`` 后写回 ``GenerationTask.result``，下游字幕渲染
（W18 SubtitleTrack）或 ``ShotDialogLine.start_time_ms/end_time_ms``
回填阶段消费这份时间戳。

设计要点
--------

- 与 ``tts_generate_worker`` 完全镜像 hotfix-4 canonical 模板：
  ``async with async_session_maker()`` + ``set_status(running)`` →
  cancel check → 业务逻辑 → cancel check → ``set_result`` →
  ``set_status(succeeded)``；失败时 rollback + 独立会话写 failed。
- 复用 :class:`DashScopeTtsApiAdapter`. ``estimate_audio_via_asr``，避免
  重复实现 Paraformer-v2 异步任务三段式（submit → poll → fetch）。
- 默认超时 ``600s``：Paraformer-v2 异步 ASR 比 CosyVoice TTS 慢 1-2 倍，
  与 adapter 默认 timeout 对齐。``fast`` 队列：单镜头视频通常 ≤ 6s 音频，
  ASR 延迟在分钟级，不应挤占视频生成 worker 的 slow 队列。
- 不做缓存命中分支：Paraformer-v2 计费按音频时长，复跑成本可控；并且
  ``keep_native`` 路径目前只对单视频生成结果做一次反推，复用价值低。
  如未来出现批量重跑需求，可参考 ``TtsCacheKey`` 模式新增
  ``AsrSubtitleCacheKey``。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.contracts.provider import ProviderConfig
from app.core.db import async_session_maker
from app.core.integrations.aliyun.dashscope_tts import DashScopeTtsApiAdapter
from app.core.task_manager import SqlAlchemyTaskStore
from app.core.task_manager.types import TaskStatus
from app.models.llm import Provider
from app.models.studio import FileItem
from app.services.llm.provider_registry import try_resolve_provider_key_from_name
from app.services.worker.async_task_support import cancel_if_requested_async
from app.services.worker.task_executor import AbstractAsyncDelegatingExecutor
from app.services.worker.task_logging import log_task_event, log_task_failure


logger = logging.getLogger(__name__)


TASK_KIND = "asr_subtitle_generate"
"""注册键：与 plan ``task_kind`` 表保持一致，避免业务侧出现拼写漂移。"""

DEFAULT_TIMEOUT_SECONDS = 600.0
"""默认超时（秒）：与 Paraformer-v2 adapter 默认 ``timeout_s=600`` 对齐。"""

_RUNNING_PROGRESS = 10
"""进入 running 时的初始进度，与 ``tts_generate_worker`` 保持一致。"""

_SUCCEEDED_PROGRESS = 100
"""任务成功完成时的最终进度。"""

_DEFAULT_LANGUAGE_HINTS: tuple[str, ...] = ("zh", "en")
"""DashScope Paraformer-v2 默认 language_hints：中英混合，覆盖 jellyfish 主用例。"""


def _coerce_str(value: object, *, default: str = "") -> str:
    """把 ``run_args`` 中的字符串字段安全规范化（去首尾空白）。"""

    if value is None:
        return default
    return str(value).strip() or default


def _coerce_language_hints(value: object) -> list[str]:
    """把 ``run_args['language_hints']`` 兜底为 ``list[str]``。

    存在原因:
        ``GenerationTask.payload`` 的 JSON 反序列化可能给出 ``None`` /
        单字符串 / 含空白元素的 list，提前标准化让 adapter 不再做防御。
        缺省走 :data:`_DEFAULT_LANGUAGE_HINTS`，避免下游误把空 list
        理解成 "禁用所有语言识别"。
    """

    if value is None:
        return list(_DEFAULT_LANGUAGE_HINTS)
    if isinstance(value, str):
        item = value.strip()
        return [item] if item else list(_DEFAULT_LANGUAGE_HINTS)
    if isinstance(value, (list, tuple)):
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return cleaned or list(_DEFAULT_LANGUAGE_HINTS)
    return list(_DEFAULT_LANGUAGE_HINTS)


async def _resolve_dashscope_provider_config(session: AsyncSession) -> ProviderConfig:
    """加载一条注册到 ``aliyun_bailian`` 的 Provider 行并构造 ProviderConfig。

    与 ``tts_generate_worker._resolve_dashscope_provider_config`` 保持同源
    实现，避免跨文件引用造成 import 循环；DashScope CosyVoice 与
    Paraformer-v2 共享同一套 API key，因此凭据解析逻辑完全一致。

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
        "asr_subtitle_generate requires an aliyun_bailian (DashScope) provider "
        "with non-empty api_key"
    )


async def _resolve_public_audio_url(
    session: AsyncSession, *, file_id: str
) -> str:
    """从 ``video_file_id`` 解析出 DashScope Paraformer 可访问的公网 URL。

    DashScope Paraformer-v2 仅支持公网 HTTP/HTTPS URL（不支持 oss:// 或本地路径）。
    本 worker 直接复用 ``storage.get_file_info`` 拿到的 ``info.url``，要求底层
    storage 已配置 ``s3_public_base_url``（CloudFront / 自建反代等），且对应对象
    必须是 public-read 或经签名 URL 形式可访问。

    Args:
        session: 当前 worker 的 async session（用于读 FileItem 行）。
        file_id: 待反推字幕的源 FileItem ID（type 应为 ``video`` 或 ``audio``）。

    Returns:
        FileItem 对应对象存储的公网 URL。

    Raises:
        LookupError: file_id 不存在或无 storage_key。
        RuntimeError: storage 元信息查询失败导致无法构造 public URL。
    """

    file_obj = await session.get(FileItem, file_id)
    if file_obj is None:
        raise LookupError(f"FileItem not found: file_id={file_id}")
    storage_key = (file_obj.storage_key or "").strip()
    if not storage_key:
        raise LookupError(
            f"FileItem has empty storage_key, cannot build public URL: file_id={file_id}"
        )
    info = await storage.get_file_info(key=storage_key)
    if not info.url:
        raise RuntimeError(
            f"storage.get_file_info returned empty URL for file_id={file_id}"
        )
    return info.url


async def run_asr_subtitle_generate_task(
    task_id: str,
    run_args: dict[str, Any],
) -> None:
    """异步 runner：用 Paraformer-v2 反推视频/音频字幕并写回任务存储。

    输入 (``run_args``):
        - ``video_file_id`` (str, required): 源 FileItem ID。FileItem.type 必须
          是 ``video`` 或 ``audio``，且对应对象存储 key 必须可被解析为公网 URL。
        - ``language_hints`` (list[str], optional, default ``["zh", "en"]``):
          DashScope Paraformer language_hints；中英混合是 jellyfish 主用例。

    输出（写入 ``store.set_result`` 的 dict）:
        - ``source_file_id``: 输入 video_file_id；
        - ``audio_url``: 实际送往 Paraformer 的公网 URL（便于排障）；
        - ``language_hints``: 实际生效的 language_hints；
        - ``duration_ms``: 字幕末尾时间戳（即音频可识别时长，0 表示静音/识别失败）；
        - ``word_timestamps``: ``[{text, begin_ms, end_ms}, ...]``。

    异常处理:
        与 ``tts_generate_worker`` 一致：try 中 rollback、独立会话写 failed、
        再向上抛由 ``AbstractAsyncDelegatingExecutor`` 转换为 Celery 失败状态。
    """

    video_file_id = _coerce_str(run_args.get("video_file_id"))
    if not video_file_id:
        raise ValueError(
            "asr_subtitle_generate requires non-empty video_file_id in run_args"
        )
    language_hints = _coerce_language_hints(run_args.get("language_hints"))

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

            audio_url = await _resolve_public_audio_url(
                session, file_id=video_file_id
            )

            provider_cfg = await _resolve_dashscope_provider_config(session)

            adapter = DashScopeTtsApiAdapter()
            word_timestamps = await adapter.estimate_audio_via_asr(
                cfg=provider_cfg,
                audio_url=audio_url,
                timeout_s=DEFAULT_TIMEOUT_SECONDS,
            )

            if await cancel_if_requested_async(
                store=store, task_id=task_id, session=session
            ):
                log_task_event(TASK_KIND, task_id, "cancelled", stage="after_execute")
                return

            duration_ms = (
                max(item.end_ms for item in word_timestamps) if word_timestamps else 0
            )

            payload: dict[str, Any] = {
                "source_file_id": video_file_id,
                "audio_url": audio_url,
                "language_hints": language_hints,
                "duration_ms": int(duration_ms),
                "word_timestamps": [ts.model_dump() for ts in word_timestamps],
            }
            await store.set_result(task_id, payload)
            await store.set_progress(task_id, _SUCCEEDED_PROGRESS)
            await store.set_status(task_id, TaskStatus.succeeded)
            await session.commit()
            log_task_event(
                TASK_KIND,
                task_id,
                "succeeded",
                source_file_id=video_file_id,
                duration_ms=int(duration_ms),
                word_count=len(word_timestamps),
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


def build_asr_subtitle_generate_executor() -> AbstractAsyncDelegatingExecutor:
    """构造与 ``task_executor_registry`` 兼容的 ASR 字幕反推执行器实例。

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
        runner=run_asr_subtitle_generate_task,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
    )


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "TASK_KIND",
    "build_asr_subtitle_generate_executor",
    "run_asr_subtitle_generate_task",
]
