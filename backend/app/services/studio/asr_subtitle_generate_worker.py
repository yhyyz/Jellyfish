"""ASR 字幕反推 worker（P3 W17 收尾，Decision D 修订；W19b 链式补齐）。

为什么存在
----------

P3 剧情带货链路在 W17 引入两条音轨路径：

- ``silent_with_tts``（默认）：丢弃模型自带音轨，由 ``tts_generate`` 合成 TTS
  音频覆盖，``word_timestamps`` 来自 CosyVoice synthesize；
- ``keep_native``（W17 收尾启用，Decision D 修订的逃生口）：保留视频生成
  模型自带原音，把 ASR 反推得到的字级时间戳作为字幕来源，配合保留口型场景。

本 worker 服务 ``keep_native`` 路径：把已落库的 video / audio FileItem
对应的对象存储 public URL 送进 DashScope Paraformer-v2 异步 ASR，拿到
``list[TtsWordTimestamp]`` 后写回 ``GenerationTask.result``，并在 result
中带上 ``shot_id``（B6）方便下游消费方按镜头维度做关联查询。

链式派发（W19b 补齐 B3/B6）
---------------------------

历史实现到这里就结束（worker 是叶子节点）：``run_args`` 中只带
``video_file_id`` / ``language_hints``，结果里只有 ``word_timestamps``，
前端必须显式 POST ``/commerce/shot-subtitle-render`` 才能把字级时间戳
渲染成 .ass。这与 ``silent_with_tts`` 路径有 ``chapter_av_planner`` 编排
形成不对称的客户端工作流。

本 worker 现在接收两个新参数：

- ``shot_id``: 字幕所属镜头 ID。写入 ``GenerationTaskLink``（resource_type=
  ``subtitle`` / relation_type=``shot``），让下游 SubtitleTrack 等查询
  能反向回到 ASR 任务；同时写进 result 让前端任务详情可直接展示。
- ``style_id``: 渲染字幕用的 SubtitleStyle ID。``run_video_generation_task``
  在 keep_native 分支 :func:`_resolve_default_subtitle_style_id` 解析出来。

ASR 主流程成功 commit 之后，本 worker 再开一个独立 session 调
:py:meth:`CommerceTaskDispatchService.enqueue_shot_subtitle_render`
落子任务行 + commit + dispatch_after_commit。链式派发任何异常都仅记录
warning，不向上抛——ASR 主任务已 commit 成功，链式失败不应回滚 ASR 自身
的 succeeded 状态。

设计要点
--------

- 与 ``tts_generate_worker`` 完全镜像 hotfix-4 canonical 模板：
  ``async with async_session_maker()`` + ``set_status(running)`` →
  cancel check → 业务逻辑 → cancel check → ``set_result`` →
  ``set_status(succeeded)``；失败时 rollback + 独立会话写 failed。
- 复用 :class:`DashScopeTtsApiAdapter`. ``estimate_audio_via_asr``，避免
  重复实现 Paraformer-v2 异步任务三段式（submit → poll → fetch）。
- 默认超时 ``600s``：Paraformer-v2 异步 ASR 比 CosyVoice TTS 慢 1-2 倍，
  与 adapter 默认 timeout 对齐。``fast`` 队列：单镜头视频通常 ≤ 6s 音频,
  ASR 延迟在分钟级，不应挤占视频生成 worker 的 slow 队列。
- 不做缓存命中分支：Paraformer-v2 计费按音频时长，复跑成本可控；并且
  ``keep_native`` 路径目前只对单视频生成结果做一次反推，复用价值低。
  如未来出现批量重跑需求，可参考 ``TtsCacheKey`` 模式新增
  ``AsrSubtitleCacheKey``。
"""

from __future__ import annotations

import asyncio
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
from app.models.task_links import GenerationTaskLink
from app.services.commerce.task_dispatch import CommerceTaskDispatchService
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

_CHAIN_DISPATCH_SOURCE = "asr_paraformer_v2"
"""链式派发 ``shot_subtitle_render`` 时写进 result 的 source 标记，
与 ``SubtitleSource.asr_paraformer_v2`` 枚举值保持一致。"""

_LINK_RESOURCE_TYPE_SUBTITLE = "subtitle"
"""``GenerationTaskLink.resource_type`` 取值，标记关联资源是字幕。"""

_LINK_RELATION_TYPE_SHOT = "shot"
"""``GenerationTaskLink.relation_type`` 取值，标记关联业务实体是镜头。"""


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

    本地开发回退（W19b-T2c）：当 ``info.url`` 指向不可被 DashScope 访问的
    内网/本机地址（典型如 ``http://127.0.0.1:9000/...`` 的本地 minio），
    自动降级为 "下载本地对象 → 上传到环境变量 ``ASR_PUBLIC_BUCKET``
    指定的公网 S3 桶 → 用 ``ASR_PUBLIC_CDN_BASE`` 作为 CDN 前缀拼出 HTTPS URL"。
    这条回退仅对 ``localhost`` / ``127.`` / ``10.`` / ``192.168.`` /
    ``172.`` 段生效，避免在生产把已 CDN 化的 URL 重复二次上传。

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
    if _looks_local_only(info.url):
        return await _republish_to_public_cdn(storage_key=storage_key)
    return info.url


_LOCAL_HOST_PREFIXES = (
    "http://localhost",
    "https://localhost",
    "http://127.",
    "https://127.",
    "http://10.",
    "https://10.",
    "http://192.168.",
    "https://192.168.",
)


def _looks_local_only(url: str) -> bool:
    """识别一个 storage URL 是否只对本机 / 内网可见，无法被外部 ASR 拉取。"""
    lowered = url.strip().lower()
    if any(lowered.startswith(prefix) for prefix in _LOCAL_HOST_PREFIXES):
        return True
    # 172.16.0.0 - 172.31.255.255 是 RFC1918 私有段，逐段判断更直观
    for second in range(16, 32):
        if lowered.startswith(f"http://172.{second}.") or lowered.startswith(
            f"https://172.{second}."
        ):
            return True
    return False


async def _republish_to_public_cdn(*, storage_key: str) -> str:
    """把内网对象重新上传到公网 S3 桶并返回 CDN URL。

    依赖运行时环境变量：
    - ``ASR_PUBLIC_BUCKET``: 公网可读 S3 桶名称（必填，否则抛错让外层失败更清晰）。
    - ``ASR_PUBLIC_CDN_BASE``: CDN/Distribution 域名（带协议，必填）。
    - ``ASR_PUBLIC_PREFIX``: 桶内 key 前缀（可选，默认 ``tmp/asr-bridge``）。

    具体策略：先 ``storage.download_object_bytes`` 把本机 minio 上的二进制内容
    拉下来；再用 boto3 写到外部桶；最后拼出 ``{cdn_base}/{prefix}/{basename}``。
    单次上传命中即返回，不做去重缓存（DashScope 任务级 idempotency 由调用侧
    保证，此处只关心 "目标 URL 公网可读"）。
    """
    import os
    import boto3
    from botocore.config import Config as BotoConfig

    public_bucket = os.environ.get("ASR_PUBLIC_BUCKET", "").strip()
    public_cdn = os.environ.get("ASR_PUBLIC_CDN_BASE", "").strip().rstrip("/")
    if not public_bucket or not public_cdn:
        raise RuntimeError(
            "Local-only storage URL detected but ASR_PUBLIC_BUCKET / "
            "ASR_PUBLIC_CDN_BASE not configured; cannot publish to public CDN"
        )
    prefix = os.environ.get("ASR_PUBLIC_PREFIX", "tmp/asr-bridge").strip("/")

    data = await storage.download_file(key=storage_key)
    base_name = storage_key.rsplit("/", 1)[-1] or storage_key.replace("/", "_")
    public_key = f"{prefix}/{base_name}" if prefix else base_name

    def _put() -> None:
        client = boto3.client("s3", config=BotoConfig(retries={"max_attempts": 3}))
        client.put_object(
            Bucket=public_bucket,
            Key=public_key,
            Body=data,
            ContentType="video/mp4",
        )

    await asyncio.to_thread(_put)
    return f"{public_cdn}/{public_key}"


async def _chain_dispatch_subtitle_render(
    *,
    shot_id: str,
    style_id: str,
    word_timestamps_payload: list[dict[str, Any]],
) -> None:
    """ASR 主任务 commit 之后链式派发 ``shot_subtitle_render``（B3/B6）。

    存在原因：
        让 ``keep_native`` 路径与 ``silent_with_tts`` 路径保持对称——前端
        不再需要在 ASR 成功后手动 POST ``/commerce/shot-subtitle-render``。

    实现要点：
        - 独立开一个新 session 而非复用 ASR worker 的主 session：主 session
          已经在外层 commit 关闭，且本步逻辑必须在 commit 之后执行（必须
          先 ASR 自身落地、再触发下游）。
        - 使用 :py:meth:`CommerceTaskDispatchService.dispatch_after_commit`
          严格遵循 W19b commit-before-dispatch 契约。
        - 异常吞 + warning：ASR 主任务已 commit 成功，下游链式派发失败
          不应回滚已成功的 ASR 状态。

    Args:
        shot_id: 字幕所属镜头 ID。
        style_id: 渲染字幕的 SubtitleStyle ID。
        word_timestamps_payload: 已 ``model_dump()`` 过的字级时间戳 list[dict]，
            字段 ``text`` / ``begin_ms`` / ``end_ms``。
    """

    if not (shot_id and style_id and word_timestamps_payload):
        return

    try:
        async with async_session_maker() as chain_session:
            chain_dispatcher = CommerceTaskDispatchService(chain_session)
            render_descriptor = await chain_dispatcher.enqueue_shot_subtitle_render(
                body={
                    "shot_id": shot_id,
                    "style_id": style_id,
                    "word_timestamps": word_timestamps_payload,
                    "source": _CHAIN_DISPATCH_SOURCE,
                }
            )
            await chain_session.commit()
            chain_dispatcher.dispatch_after_commit(render_descriptor)
    except Exception as exc:  # noqa: BLE001 - 链式失败不应回滚已 commit 的 ASR 主任务
        logger.warning(
            "asr_subtitle_generate chain dispatch shot_subtitle_render failed: "
            "shot_id=%s style_id=%s err=%s",
            shot_id,
            style_id,
            exc,
        )


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
        - ``shot_id`` (str, optional): 字幕所属镜头 ID。提供时本 worker 会
          额外写一行 :class:`GenerationTaskLink`（B6），并在 commit 后链式
          派发 ``shot_subtitle_render``（B3）。Legacy 调用方可不传，行为
          降级为旧的“仅返回 word_timestamps”叶子节点。
        - ``style_id`` (str, optional): 链式派发 ``shot_subtitle_render``
          所需的 SubtitleStyle ID；缺失时跳过链式派发但 ASR 仍成功返回。

    输出（写入 ``store.set_result`` 的 dict）:
        - ``shot_id`` (str | None): 镜头 ID（B6）；旧调用方不传 shot_id 时为 None。
        - ``source_file_id``: 输入 video_file_id；
        - ``audio_url``: 实际送往 Paraformer 的公网 URL（便于排障）；
        - ``language_hints``: 实际生效的 language_hints；
        - ``duration_ms``: 字幕末尾时间戳（即音频可识别时长，0 表示静音/识别失败）；
        - ``word_timestamps``: ``[{text, begin_ms, end_ms}, ...]``。

    异常处理:
        与 ``tts_generate_worker`` 一致：try 中 rollback、独立会话写 failed、
        再向上抛由 ``AbstractAsyncDelegatingExecutor`` 转换为 Celery 失败状态。
        链式派发的异常被 :func:`_chain_dispatch_subtitle_render` 内部吞掉，
        不影响 ASR 自身已 commit 的成功状态。
    """

    video_file_id = _coerce_str(run_args.get("video_file_id"))
    if not video_file_id:
        raise ValueError(
            "asr_subtitle_generate requires non-empty video_file_id in run_args"
        )
    language_hints = _coerce_language_hints(run_args.get("language_hints"))
    shot_id = _coerce_str(run_args.get("shot_id"))
    style_id = _coerce_str(run_args.get("style_id"))

    word_timestamps_payload: list[dict[str, Any]] = []

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
            word_timestamps_payload = [ts.model_dump() for ts in word_timestamps]

            # B6: result 中显式带 shot_id，避免前端任务详情/排障日志必须
            # 回查 GenerationTaskLink 才能定位到镜头。
            payload: dict[str, Any] = {
                "shot_id": shot_id or None,
                "source_file_id": video_file_id,
                "audio_url": audio_url,
                "language_hints": language_hints,
                "duration_ms": int(duration_ms),
                "word_timestamps": word_timestamps_payload,
            }
            await store.set_result(task_id, payload)

            # B6: 写一行 GenerationTaskLink，让 SubtitleTrack 等下游查询
            # 能按 shot_id 反向找到 ASR 任务。仅在 shot_id 提供时写入，
            # 兼容仍走旧契约（无 shot_id）的 legacy 调用方。
            if shot_id:
                session.add(
                    GenerationTaskLink(
                        task_id=task_id,
                        resource_type=_LINK_RESOURCE_TYPE_SUBTITLE,
                        relation_type=_LINK_RELATION_TYPE_SHOT,
                        relation_entity_id=shot_id,
                    )
                )

            await store.set_progress(task_id, _SUCCEEDED_PROGRESS)
            await store.set_status(task_id, TaskStatus.succeeded)
            await session.commit()
            log_task_event(
                TASK_KIND,
                task_id,
                "succeeded",
                source_file_id=video_file_id,
                shot_id=shot_id or None,
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

    # B3: ASR 主任务 commit 完成后链式派发 shot_subtitle_render。必须放在
    # async with 之外（主 session 已 commit 关闭），并通过新的 session 严格
    # 按 W19b commit-before-dispatch 契约执行。
    await _chain_dispatch_subtitle_render(
        shot_id=shot_id,
        style_id=style_id,
        word_timestamps_payload=word_timestamps_payload,
    )


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
