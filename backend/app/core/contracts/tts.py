"""TTS 共享输入输出契约（P3 W17 引入）。

集中存放 TTS 流程中跨层共用的 Pydantic 模型：
- TtsWordTimestamp：字级时间戳片段
- TtsRequest：合成请求入参
- TtsResult：合成结果出参（含 cache_hit 标记）
- TtsCacheKey：(text, voice_pack_id, speed) 三元组，统一产出 sha256 hash

与 ORM 层 `app.models.voice_pack.TtsCache` 的 cache_key 列保持同源；
所有调用方必须通过 TtsCacheKey.to_hash() 计算键，避免散落实现导致命中失效。
"""

from __future__ import annotations

import hashlib
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class TtsWordTimestamp(BaseModel):
    """字级时间戳（CosyVoice / Paraformer-v2 共用）。"""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., description="文本片段（汉字/英文词）")
    begin_ms: int = Field(..., ge=0, description="起始毫秒")
    end_ms: int = Field(..., ge=0, description="结束毫秒")


class TtsRequest(BaseModel):
    """TTS 合成请求。

    speed 限定 [0.5, 2.0] 与多数主流供应商范围一致；
    audio_format 暂只允许 mp3/wav/pcm/opus 四种，避免后端 minio 出现非主流编码。
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1, description="待合成文本")
    voice_pack_id: str = Field(..., description="音色包 ID")
    provider_voice_id: str = Field(..., description="供应商侧音色 ID（如 longxiaochun_v2）")
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="语速 0.5-2.0")
    sample_rate: int = Field(default=22050, description="采样率")
    audio_format: str = Field(
        default="mp3",
        pattern=r"^(mp3|wav|pcm|opus)$",
        description="输出格式",
    )
    enable_word_timestamps: bool = Field(
        default=True,
        description="启用字级时间戳（仅 cosyvoice-v2 系列支持）",
    )
    language_hints: list[str] = Field(
        default_factory=lambda: ["zh"],
        description="语言提示",
    )


class TtsResult(BaseModel):
    """TTS 合成结果。

    cache_hit 标记本次响应是否来自 tts_cache 命中（True 时不产生供应商成本）；
    provider_request_id 用于跨日志追踪原始供应商任务。
    """

    model_config = ConfigDict(extra="forbid")

    audio_file_id: str = Field(..., description="音频 FileItem ID（已落 minio）")
    audio_format: str = Field(..., description="实际输出格式")
    duration_ms: int = Field(..., ge=0, description="音频时长毫秒")
    word_timestamps: list[TtsWordTimestamp] = Field(
        default_factory=list,
        description="字级时间戳（启用时）",
    )
    provider_request_id: Optional[str] = Field(
        None,
        description="供应商侧 task_id（追踪用）",
    )
    cache_hit: bool = Field(default=False, description="是否命中 tts_cache")


class TtsCacheKey(BaseModel):
    """tts_cache 唯一键三元组。

    to_hash() 是 cache_key 列值的唯一权威生成口径：
    sha256(f"{text}|{voice_pack_id}|{speed:.3f}")。
    speed 固定 3 位小数，避免浮点表示差异（1.0 vs 1.000）造成 hash 错位。
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    voice_pack_id: str
    speed: float

    def to_hash(self) -> str:
        """计算稳定 sha256 hash 作为 tts_cache.cache_key。"""
        payload = f"{self.text}|{self.voice_pack_id}|{self.speed:.3f}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TtsVoiceCapability(BaseModel):
    """音色能力描述：供应商→音色支持哪些功能（语言/字级时间戳/采样率等）。

    用于路由层在合成前做能力校验（如请求字级时间戳但音色不支持时直接 422）。
    """

    model_config = ConfigDict(extra="forbid")

    voice_pack_id: str = Field(..., description="音色包 ID")
    languages: list[str] = Field(default_factory=list, description="支持语言列表")
    supports_word_timestamps: bool = Field(
        default=False,
        description="是否支持字级时间戳",
    )
    sample_rates: list[int] = Field(
        default_factory=list,
        description="支持的采样率",
    )
    formats: list[str] = Field(
        default_factory=list,
        description="支持的输出格式",
    )


__all__ = [
    "TtsWordTimestamp",
    "TtsRequest",
    "TtsResult",
    "TtsCacheKey",
    "TtsVoiceCapability",
]
