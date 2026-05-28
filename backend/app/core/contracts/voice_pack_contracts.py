"""自定义音色训练跨层 DTO（P5 W29 引入）。

为什么存在：
    P5 W29 在 P3 W17 已落地的 ``VoicePack`` 只读链路之上扩出"用户上传 →
    DashScope voice clone → 轮询 → 落库"完整管线。该管线需要在
    HTTP API 层（multipart upload）/ service 层（音频校验 + DashScope SDK）
    / worker 层（轮询）三处共享同一组数据契约；按 AGENTS.md §9，跨层 DTO
    必须沉淀到 ``app.core.contracts``，禁止散落到 schemas / services 内部。

做什么：
    - :class:`CustomVoiceCreateRequest`：HTTP POST 表单字段（不含 sample 文件
      本身）+ DashScope ``create_voice`` 调用所需的全部参数。
    - :class:`CustomVoiceCreateResponse`：HTTP POST 立即响应（``202 Accepted``）。
    - :class:`CustomVoiceStatusResponse`：HTTP GET ``/status`` 单条音色状态。
    - :class:`AudioMetadataValidation`：前端 / 后端共享的音频元信息校验结果，
      把"满足 DashScope 输入约束"具象成一组结构化字段，避免散在两端。

校验规则严格对齐 DashScope CosyVoice voice-enrollment 官方约束（参考
W29 instructions：format/duration/size/sample_rate/channels）；prefix 用
``regex`` 限定 ASCII slugify，禁止 passthrough 用户原始输入。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.types import VoiceCloneStatus, VoiceRegion


# DashScope CosyVoice voice clone 输入约束常量（与官方 SDK schema 对齐）。
# - 音频格式：仅支持 wav / mp3 / m4a。
# - 时长：10-60 秒（推荐 10-20 秒），过短训练效果差，过长会被截断。
# - 大小：≤10 MB。
# - 采样率：≥16 kHz。
# - 声道：1（mono）或 2（stereo，会取首声道）。
ALLOWED_AUDIO_FORMATS: frozenset[str] = frozenset({"wav", "mp3", "m4a"})

# DashScope CosyVoice 当前对外可选的 voice clone 目标合成模型。
# 同 voice_id 不能跨模型迁移，需要严格 Literal 限定避免误传。
ALLOWED_TARGET_MODELS: frozenset[str] = frozenset(
    {"cosyvoice-v3.5-plus", "cosyvoice-v3-plus"}
)


class CustomVoiceCreateRequest(BaseModel):
    """自定义音色创建请求 DTO。

    用于 ``POST /api/v1/commerce/voice-packs/custom`` multipart 表单上的非文件
    字段；sample 音频本身通过 :class:`fastapi.UploadFile` 单独传入路由 handler。

    校验规则：
        - ``prefix``：DashScope 要求 ≤10 字符、仅数字/字母/下划线（slugify）。
          前端必须先做 sanitize 再提交，避免直接 passthrough 用户原始输入。
        - ``target_model``：必须落在
          :data:`ALLOWED_TARGET_MODELS` 集合内（``cosyvoice-v3.5-plus`` /
          ``cosyvoice-v3-plus``）；一旦落库即与 voice_id 绑死。
        - ``region``：必须落在 :class:`VoiceRegion` 枚举内
          （``cn-beijing`` / ``ap-singapore``）。
        - ``display_name``：用户可见名称，UI 展示用，≤64 字符。
        - ``language_hints``：可选；DashScope ``create_voice`` 透传的语言
          提示（如 ``["zh"]`` / ``["en"]`` / ``["ja"]``），影响合成发音表现。
        - ``description``：可选业务说明，≤255 字符。
        - ``archetype_hint``：可选 BrandArchetype 提示（与 W17 系统音色
          ``archetype_hint`` 对齐），用于品牌人格自动推荐音色。
    """

    prefix: str = Field(
        ...,
        pattern=r"^[A-Za-z0-9_]{1,10}$",
        description="DashScope voice clone prefix；≤10 字符，仅数字/字母/下划线",
    )
    target_model: Literal["cosyvoice-v3.5-plus", "cosyvoice-v3-plus"] = Field(
        ...,
        description="DashScope 目标合成模型；voice_id 与此值绑死，跨模型升级须重新创建",
    )
    region: VoiceRegion = Field(
        ...,
        description="DashScope 区域端点（cn-beijing / ap-singapore）",
    )
    display_name: str = Field(
        ...,
        max_length=64,
        min_length=1,
        description="用户可见的音色展示名称",
    )
    language_hints: list[str] | None = Field(
        default=None,
        description="可选 language hints 透传给 DashScope create_voice",
    )
    description: str | None = Field(
        default=None,
        max_length=255,
        description="可选业务描述",
    )
    archetype_hint: str | None = Field(
        default=None,
        description="可选 BrandArchetype 提示，用于自动推荐",
    )


class CustomVoiceCreateResponse(BaseModel):
    """自定义音色创建立即响应 DTO（``202 Accepted``）。

    DashScope ``create_voice`` 是异步训练，调用即返回 voice_id 但状态停留
    在 ``DEPLOYING``；本响应回给前端 voice_pack_id（DB 行主键）+
    ``clone_status=deploying``，前端凭它去 ``GET /status`` 轮询直到
    ``ready`` / ``failed``。
    """

    model_config = ConfigDict(from_attributes=True)

    voice_pack_id: str = Field(..., description="VoicePack 行主键")
    clone_status: VoiceCloneStatus = Field(
        ..., description="当前 clone 状态；新创建必为 deploying"
    )
    created_at: datetime = Field(..., description="VoicePack 行入库时刻")


class CustomVoiceStatusResponse(BaseModel):
    """单条音色状态查询响应（``GET /status``）。

    用于前端 VoicePackLibrary 自动轮询 ``deploying`` 行；``ready`` /
    ``failed`` 终态后停止轮询。
    """

    model_config = ConfigDict(from_attributes=True)

    voice_pack_id: str
    clone_status: VoiceCloneStatus
    provider_voice_id: str | None = Field(
        None, description="DashScope 返回的 voice_id；ready 后填充"
    )
    failure_reason: str | None = Field(
        None, description="failed 时的失败原因（取 description 末尾备注）"
    )
    cloned_at: datetime | None = Field(
        None, description="ready 时的完成时间戳；其他状态为 NULL"
    )


class AudioMetadataValidation(BaseModel):
    """音频元信息校验结果 DTO（前后端共享）。

    前端在用户选定文件后、点击提交前用 ``AudioContext.decodeAudioData`` 拿
    到对应字段做客户端校验；后端在 multipart 接收后用 ``soundfile`` 二次校
    验，把同一组约束写在同一个契约里避免漂移。

    所有字段均为强约束：任一不满足必须 ``422`` reject。
    """

    model_config = ConfigDict(extra="forbid")

    format: Literal["wav", "mp3", "m4a"] = Field(
        ..., description="音频格式（wav / mp3 / m4a）"
    )
    duration_sec: float = Field(
        ...,
        ge=10.0,
        le=60.0,
        description="时长秒数；DashScope 要求 10-60 秒，推荐 10-20 秒",
    )
    size_bytes: int = Field(
        ...,
        ge=1,
        le=10 * 1024 * 1024,
        description="文件大小字节；上限 10 MB",
    )
    sample_rate_hz: int = Field(
        ...,
        ge=16000,
        description="采样率 Hz；DashScope 要求 ≥16 kHz",
    )
    channels: int = Field(
        ...,
        ge=1,
        le=2,
        description="声道数；1=mono / 2=stereo（取首声道）",
    )


__all__ = [
    "ALLOWED_AUDIO_FORMATS",
    "ALLOWED_TARGET_MODELS",
    "AudioMetadataValidation",
    "CustomVoiceCreateRequest",
    "CustomVoiceCreateResponse",
    "CustomVoiceStatusResponse",
]
