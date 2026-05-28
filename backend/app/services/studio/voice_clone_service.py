"""自定义音色训练服务（P5 W29 引入）。

为什么存在：
    P5 W29 在 P3 W17 已落地的"系统级 voice pack 只读 + 启动 seed"链路之上
    扩出"用户上传 → DashScope CosyVoice voice-enrollment → 异步轮询 → 落库
    成可用 VoicePack"完整管线。该管线被两条调用路径共享：

    1. HTTP API（``POST /api/v1/commerce/voice-packs/custom`` multipart upload）
    2. 管理脚本（``backend/scripts/seed_overseas_voice_packs.py`` 海外音色 seed）

    把"音频校验 + OSS 转存 + DashScope 创建 + DB 持久化"4 步骤封装为本
    service 让两条路径共用同一执行路径，避免在 W19b 双引擎事务边界上重复
    实现 commit-before-dispatch 契约。

按 AGENTS.md §4 严格分层：API 层只调本 service；本 service 不直接绑
FastAPI / DashScope 类型，HTTP 调用细节封在 :class:`_DashScopeVoiceClient`
内部，方便测试 monkeypatch 替换。

按 W19b 契约：:func:`persist_voice_pack` 内部 ``await db.commit()`` 后再
返回；caller 在 return 之后才能 dispatch poll task（commit-then-send）。
"""

from __future__ import annotations

import asyncio
import io
import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import dashscope
from dashscope.audio.tts_v2 import VoiceEnrollmentService
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.contracts.voice_pack_contracts import (
    ALLOWED_AUDIO_FORMATS,
    AudioMetadataValidation,
    CustomVoiceCreateRequest,
)
from app.models.types import VoiceCloneStatus, VoiceGender, VoiceProvider, VoiceRegion
from app.models.voice_pack import VoicePack


logger = logging.getLogger(__name__)


# DashScope CosyVoice voice clone 输入约束（与 contracts 同源，避免漂移）。
MIN_DURATION_SEC: float = 10.0
MAX_DURATION_SEC: float = 60.0
MAX_SIZE_BYTES: int = 10 * 1024 * 1024
MIN_SAMPLE_RATE_HZ: int = 16000
MAX_CHANNELS: int = 2

# DashScope 区域端点常量；切换 base_http_api_url 时使用。
_DASHSCOPE_BASE_URL_BEIJING: str = "https://dashscope.aliyuncs.com/api/v1"
_DASHSCOPE_BASE_URL_SINGAPORE: str = "https://dashscope-intl.aliyuncs.com/api/v1"

# voice sample 在 minio bucket 中的 key 前缀；与 ``files.py`` 的 ``prefix`` 习惯一致。
_VOICE_SAMPLE_PREFIX = "voice-clone-samples"

# 预签名 URL 默认有效期：2 小时。DashScope 创建后整个轮询过程最长 5 分钟，
# 但若高峰期排队较久仍需让 URL 在训练期间持续可访问，留较大余量。
_PRESIGNED_URL_EXPIRES_SEC: int = 7200

# 全局锁：DashScope SDK 通过模块级全局变量切换 base_http_api_url，多线程 / 多
# 请求并发调用时必须串行，否则可能把北京请求误投到新加坡。
_REGION_SWITCH_LOCK = threading.Lock()


@dataclass(frozen=True)
class AudioValidationFailure:
    """音频校验失败原因（用于前端友好提示）。

    Attributes:
        field: 失败的字段名（``format`` / ``duration_sec`` / ``size`` /
            ``sample_rate_hz`` / ``channels``）。
        expected: 期望约束（如 "10.0-60.0"）。
        actual: 实际值的字符串表示。
    """

    field: str
    expected: str
    actual: str

    def to_dict(self) -> dict[str, str]:
        """转为 JSON 可序列化的 dict 供 HTTP 响应使用。"""
        return {"field": self.field, "expected": self.expected, "actual": self.actual}


def validate_audio_metadata(
    file_bytes: bytes,
    declared_format: str,
) -> tuple[AudioMetadataValidation | None, list[AudioValidationFailure]]:
    """校验上传音频是否满足 DashScope voice clone 输入约束。

    校验项严格对应官方约束（参考 W29 instructions）：

    - format ∈ {wav, mp3, m4a}
    - 10s ≤ duration ≤ 60s
    - size ≤ 10 MB
    - sample_rate ≥ 16 kHz
    - channels ∈ {1, 2}

    Args:
        file_bytes: 上传文件的字节流（已被 size cap 限制读完）。
        declared_format: 客户端声明的音频格式后缀（``wav`` / ``mp3`` / ``m4a``）。

    Returns:
        二元组 ``(validation, failures)``：

        - 全部约束满足时，``validation`` 是非 ``None`` 的
          :class:`AudioMetadataValidation`，``failures`` 是空 list。
        - 任一约束失败时，``validation`` 为 ``None``，``failures`` 列出全部失败项
          （不会短路，便于前端一次提示完）。

    内部逻辑：
        soundfile 通常通过 libsndfile 解析 wav / flac，对 mp3 / m4a 的支持取决
        于编译选项；这里在 try/except 中容错——任何解析异常一律视为 "format
        失败"，让前端提示用户重新上传正确格式的文件。
    """

    failures: list[AudioValidationFailure] = []

    if declared_format not in ALLOWED_AUDIO_FORMATS:
        failures.append(
            AudioValidationFailure(
                field="format",
                expected=f"one of {sorted(ALLOWED_AUDIO_FORMATS)}",
                actual=declared_format,
            )
        )

    size_bytes = len(file_bytes)
    if size_bytes > MAX_SIZE_BYTES:
        failures.append(
            AudioValidationFailure(
                field="size",
                expected=f"<= {MAX_SIZE_BYTES} bytes",
                actual=f"{size_bytes} bytes",
            )
        )

    duration_sec, sample_rate_hz, channels = _probe_audio_dimensions(file_bytes)
    if duration_sec is None or sample_rate_hz is None or channels is None:
        failures.append(
            AudioValidationFailure(
                field="format",
                expected="parseable audio",
                actual="unparseable",
            )
        )
        return None, failures

    if not MIN_DURATION_SEC <= duration_sec <= MAX_DURATION_SEC:
        failures.append(
            AudioValidationFailure(
                field="duration_sec",
                expected=f"{MIN_DURATION_SEC}-{MAX_DURATION_SEC}",
                actual=f"{duration_sec:.2f}",
            )
        )

    if sample_rate_hz < MIN_SAMPLE_RATE_HZ:
        failures.append(
            AudioValidationFailure(
                field="sample_rate_hz",
                expected=f">= {MIN_SAMPLE_RATE_HZ}",
                actual=str(sample_rate_hz),
            )
        )

    if channels < 1 or channels > MAX_CHANNELS:
        failures.append(
            AudioValidationFailure(
                field="channels",
                expected="1 or 2",
                actual=str(channels),
            )
        )

    if failures:
        return None, failures

    validation = AudioMetadataValidation(
        format=declared_format,  # type: ignore[arg-type]
        duration_sec=duration_sec,
        size_bytes=size_bytes,
        sample_rate_hz=sample_rate_hz,
        channels=channels,
    )
    return validation, []


def _probe_audio_dimensions(
    file_bytes: bytes,
) -> tuple[float | None, int | None, int | None]:
    """用 soundfile 探测音频时长 / 采样率 / 声道数。

    存在原因：
        soundfile 是底层 libsndfile 的轻量 Python 绑定，能稳定读出 wav / flac
        头信息；mp3 / m4a 在某些发行版上不被 libsndfile 支持。一旦解析失败统
        一返回三元 ``None``，让 :func:`validate_audio_metadata` 把它当作 format
        失败汇总到 failures 列表。

    Returns:
        ``(duration_sec, sample_rate_hz, channels)``；任一字段无法解析时
        全部为 ``None``。
    """

    try:
        import soundfile as sf  # pylint: disable=import-outside-toplevel
    except ImportError:
        logger.warning("soundfile not installed; audio metadata validation degraded")
        return None, None, None

    try:
        with sf.SoundFile(io.BytesIO(file_bytes)) as audio:
            sample_rate_hz = int(audio.samplerate)
            channels = int(audio.channels)
            frames = len(audio)
            if sample_rate_hz <= 0:
                return None, None, None
            duration_sec = frames / sample_rate_hz
            return duration_sec, sample_rate_hz, channels
    except Exception as exc:  # noqa: BLE001 - libsndfile 抛多种异常，统一兜底
        logger.info("audio probe failed: %s", exc)
        return None, None, None


async def upload_sample_to_oss(
    file_bytes: bytes,
    declared_format: str,
) -> tuple[str, str]:
    """把音频样本上传到对象存储，返回 ``(oss_key, public_url)``。

    Args:
        file_bytes: 已经过 :func:`validate_audio_metadata` 的字节流。
        declared_format: 格式后缀（用于 oss_key 命名 + content-type 推断）。

    Returns:
        二元组 ``(oss_key, public_url)``：

        - ``oss_key`` 是 minio bucket 内对象 key（含 ``voice-clone-samples/``
          前缀 + uuid hex 文件名 + 格式后缀）。
        - ``public_url`` 是公网可访问的 URL（仅当配置了
          ``s3_public_base_url`` 且 bucket policy 允许公开读时为真公网，
          否则需要在对应位置生成预签名 URL —— 见 :func:`storage.generate_presigned_url`）。

    实现要点：
        1. 复用 :mod:`app.core.storage` 抽象（与 tts_generate_worker 同样
           的写法），不直接绑死 minio / boto3 SDK。
        2. ``ACL: public-read`` 让 DashScope 后端能直接 fetch；如部署
           bucket policy 不允许设此 ACL 应在调用 DashScope 时改用预签名 URL。
    """

    fmt = declared_format.lower()
    extension = f".{fmt}"
    oss_key = f"{_VOICE_SAMPLE_PREFIX}/{uuid.uuid4().hex}{extension}"
    content_type_map = {
        "wav": "audio/wav",
        "mp3": "audio/mpeg",
        "m4a": "audio/mp4",
    }
    content_type = content_type_map.get(fmt, "application/octet-stream")

    info = await storage.upload_file(
        key=oss_key,
        data=file_bytes,
        content_type=content_type,
        extra_args={"ACL": "public-read"},
    )
    return info.key, info.url


async def create_voice_remote(
    *,
    target_model: str,
    prefix: str,
    sample_url: str,
    region: VoiceRegion,
    language_hints: list[str] | None = None,
) -> str:
    """调用 DashScope ``create_voice`` 创建音色，返回 voice_id（仍 ``DEPLOYING`` 状态）。

    Args:
        target_model: DashScope 目标合成模型（如 ``cosyvoice-v3.5-plus``）。
        prefix: ≤10 字符的 slugify 前缀；与 ``CustomVoiceCreateRequest.prefix`` 校验保持一致。
        sample_url: 公网可访问的 voice sample URL（OSS 预签名 / 公开 CDN）。
        region: DashScope 区域端点；决定调北京还是新加坡。
        language_hints: 可选语言提示透传给 DashScope。

    Returns:
        voice_id 字符串，形如 ``cosyvoice-v3.5-plus-myvoice-xxx``；
        此时音色状态为 ``DEPLOYING``，需要后续 :func:`query_clone_status` 轮询。

    实现要点：
        - DashScope SDK 是同步 SDK，必须用 :func:`asyncio.to_thread` 包裹
          避免阻塞 event loop。
        - DashScope SDK 通过模块级全局变量 ``dashscope.base_http_api_url``
          切区，多线程并发可能竞争；用 :data:`_REGION_SWITCH_LOCK` 串行化。
    """

    return await asyncio.to_thread(
        _create_voice_sync,
        target_model=target_model,
        prefix=prefix,
        sample_url=sample_url,
        region=region,
        language_hints=language_hints,
    )


def _create_voice_sync(
    *,
    target_model: str,
    prefix: str,
    sample_url: str,
    region: VoiceRegion,
    language_hints: list[str] | None,
) -> str:
    """同步实现 :func:`create_voice_remote`，被 :func:`asyncio.to_thread` 包装调用。"""

    with _REGION_SWITCH_LOCK:
        _set_region_endpoint(region)
        service = VoiceEnrollmentService()
        voice_id: str = service.create_voice(
            target_model=target_model,
            prefix=prefix,
            url=sample_url,
            language_hints=language_hints,
        )
        return voice_id


async def query_clone_status(
    *,
    voice_id: str,
    region: VoiceRegion,
) -> tuple[VoiceCloneStatus, str | None]:
    """查询 DashScope 上某条 voice clone 的当前状态。

    Args:
        voice_id: ``create_voice`` 返回的 voice_id。
        region: 创建时使用的 DashScope 区域；不能跨区查。

    Returns:
        二元组 ``(status, failure_reason)``：

        - ``DEPLOYING`` -> ``(VoiceCloneStatus.deploying, None)``
        - ``OK`` -> ``(VoiceCloneStatus.ready, None)``
        - ``UNDEPLOYED`` 或其他异常 -> ``(VoiceCloneStatus.failed, reason)``
    """

    return await asyncio.to_thread(_query_voice_sync, voice_id=voice_id, region=region)


def _query_voice_sync(
    *,
    voice_id: str,
    region: VoiceRegion,
) -> tuple[VoiceCloneStatus, str | None]:
    """同步实现 :func:`query_clone_status`，被 :func:`asyncio.to_thread` 包装调用。"""

    with _REGION_SWITCH_LOCK:
        _set_region_endpoint(region)
        service = VoiceEnrollmentService()
        try:
            output: Any = service.query_voice(voice_id=voice_id)
        except Exception as exc:  # noqa: BLE001 - SDK 抛多种异常，统一兜底
            logger.warning("query_voice raised %s for voice_id=%s", exc, voice_id)
            return VoiceCloneStatus.failed, f"query_voice error: {exc}"

    raw_status = _extract_status_from_output(output)
    if raw_status == "OK":
        return VoiceCloneStatus.ready, None
    if raw_status == "DEPLOYING":
        return VoiceCloneStatus.deploying, None
    if raw_status == "UNDEPLOYED":
        return VoiceCloneStatus.failed, "DashScope returned UNDEPLOYED"
    return VoiceCloneStatus.failed, f"unknown status: {raw_status!r}"


def _extract_status_from_output(output: Any) -> str | None:
    """从 ``query_voice`` 返回的 dict-like 提取 ``status`` 字段。

    DashScope SDK 不同版本可能把 status 放在 ``output["status"]`` 或
    ``output.get("voice", {}).get("status")``；这里做一个宽容的探测。
    """

    if isinstance(output, dict):
        if "status" in output:
            return str(output["status"]).upper()
        voice = output.get("voice")
        if isinstance(voice, dict) and "status" in voice:
            return str(voice["status"]).upper()
    return None


async def delete_voice_remote(
    *,
    voice_id: str,
    region: VoiceRegion,
) -> bool:
    """从 DashScope 删除音色（释放配额）。

    Args:
        voice_id: 待删除的 voice_id。
        region: 创建时使用的 DashScope 区域。

    Returns:
        ``True`` 表示删除成功；``False`` 表示对端不存在 / 已删（幂等容忍）。

    实现要点：
        DashScope SDK 删除不存在的 voice 会抛
        :class:`dashscope.audio.tts_v2.enrollment.VoiceEnrollmentException`，
        本函数统一捕获并返回 ``False``，让 caller（如 DELETE endpoint）能
        直接对幂等场景做 200 OK 响应而不必判异常类型。
    """

    return await asyncio.to_thread(
        _delete_voice_sync, voice_id=voice_id, region=region
    )


def _delete_voice_sync(*, voice_id: str, region: VoiceRegion) -> bool:
    """同步实现 :func:`delete_voice_remote`，被 :func:`asyncio.to_thread` 包装调用。"""

    with _REGION_SWITCH_LOCK:
        _set_region_endpoint(region)
        service = VoiceEnrollmentService()
        try:
            service.delete_voice(voice_id=voice_id)
            return True
        except Exception as exc:  # noqa: BLE001 - SDK 抛多种异常，统一兜底
            logger.info(
                "delete_voice idempotent fallback for voice_id=%s: %s", voice_id, exc
            )
            return False


def _set_region_endpoint(region: VoiceRegion) -> None:
    """切换 DashScope SDK 全局 base_http_api_url 到对应区域。

    必须在 :data:`_REGION_SWITCH_LOCK` 持有期间调用，否则可能与并发的反向
    切换竞态。SDK 在 ``call`` 时读取这个全局变量决定走哪条 endpoint。
    """

    if region == VoiceRegion.ap_singapore:
        dashscope.base_http_api_url = _DASHSCOPE_BASE_URL_SINGAPORE
    else:
        dashscope.base_http_api_url = _DASHSCOPE_BASE_URL_BEIJING


async def persist_voice_pack(
    db: AsyncSession,
    *,
    request: CustomVoiceCreateRequest,
    sample_audio_oss_key: str,
    dashscope_voice_id: str,
) -> VoicePack:
    """写入新 :class:`VoicePack` 行（``is_system=False``，``clone_status=deploying``）并 commit。

    W19b 契约：本函数内部 ``await db.commit()`` 完成后再 return；caller 必须
    在 return 之后才能 dispatch poll task（commit-then-send）。违反此契约会
    重现 race condition：worker 拉到消息时 ``db.get(VoicePack, voice_pack_id)``
    返回 ``None``，导致轮询直接失败。

    Args:
        db: 当前 HTTP 请求绑定的 :class:`AsyncSession`。
        request: 已经过 schema 校验的创建请求 DTO。
        sample_audio_oss_key: minio bucket 内 voice sample object key。
        dashscope_voice_id: ``create_voice`` 返回的 voice_id（仍 DEPLOYING 状态）。

    Returns:
        刚刚写入并 ``refresh`` 过的 :class:`VoicePack` 行。
    """

    voice_pack = VoicePack(
        id=f"clone_{uuid.uuid4().hex[:24]}",
        name=request.display_name,
        provider=VoiceProvider.aliyun_cosyvoice,
        provider_voice_id=dashscope_voice_id,
        language_code=(request.language_hints or ["zh"])[0],
        gender=VoiceGender.neutral,
        archetype_hint=request.archetype_hint,
        description=request.description or "",
        default_speed=1.0,
        is_system=False,
        sort_order=1000,
        target_model=request.target_model,
        region=request.region,
        clone_status=VoiceCloneStatus.deploying,
        sample_audio_oss_key=sample_audio_oss_key,
        cloned_at=None,
    )
    db.add(voice_pack)
    await db.commit()
    await db.refresh(voice_pack)
    return voice_pack


def utcnow_naive() -> datetime:
    """返回 UTC ``datetime``（不带 tzinfo），与 ORM ``DateTime(timezone=True)`` 兼容。

    SQLAlchemy ``DateTime(timezone=True)`` 在 SQLite 后端会把 tzinfo 抹掉，
    在 MySQL 后端则保留为 UTC；统一用 ``replace(tzinfo=None)`` 落库可避免
    跨后端时区漂移导致的相等性失效（与 task_dispatch 中 ``enqueued_at`` 同样写法）。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


__all__ = [
    "AudioValidationFailure",
    "create_voice_remote",
    "delete_voice_remote",
    "persist_voice_pack",
    "query_clone_status",
    "upload_sample_to_oss",
    "utcnow_naive",
    "validate_audio_metadata",
]
