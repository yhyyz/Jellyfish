"""音色包 + TTS 缓存模型（P3 W17 引入）。

包含两张表：
- voice_packs：跨镜头/项目复用的 TTS 音色定义；启动期由 builtin_voice_packs
  幂等 seed 系统级音色（is_system=True），用户也可上传自定义 voice clone。
- tts_cache：(text, voice_pack_id, speed) 三元组 sha256 hash 缓存，命中即复用
  既有合成音频，避免重复调用供应商（D15 决策）。

注：本模块仅引入新表，Character/StoryVariant/ShotDialogLine 关联 voice_pack_id
列由 W17-Integration-D 阶段（alembic 0009）一次性补齐，避免分散迁移。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin
from app.models.types import VoiceGender, VoiceProvider


class VoicePack(Base, TimestampMixin):
    """音色包：跨镜头/项目复用的 TTS 音色定义。

    系统级音色（is_system=True）由启动期 builtin_voice_packs 幂等 seed；
    用户也可上传自定义 voice clone（is_system=False，sample_file_id 关联训练样本）。
    archetype_hint 用于在脚本生成阶段做语义匹配（如智者-sage 倾向沉稳低音）。
    """

    __tablename__ = "voice_packs"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        comment="音色包 ID（如 cosyvoice_v2_longxiaochun）",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="展示名称（如 龙小淳）",
    )
    provider: Mapped[VoiceProvider] = mapped_column(
        String(32),
        nullable=False,
        default=VoiceProvider.aliyun_cosyvoice.value,
        server_default=VoiceProvider.aliyun_cosyvoice.value,
        index=True,
        comment="TTS 供应商",
    )
    provider_voice_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="供应商侧音色 ID（如 longxiaochun_v2）",
    )
    language_code: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="zh-CN",
        server_default="zh-CN",
        index=True,
        comment="语言代码（zh-CN / en-US / ja-JP 等）",
    )
    gender: Mapped[VoiceGender] = mapped_column(
        String(16),
        nullable=False,
        default=VoiceGender.neutral.value,
        server_default=VoiceGender.neutral.value,
        comment="声纹性别",
    )
    archetype_hint: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        default=None,
        comment="可选：与 BrandArchetype / 角色原型的语义匹配提示（如 sage / elder）",
    )
    sample_file_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("files.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
        index=True,
        comment="试听样本音频 file_id（系统音色可选填，自定义克隆音色为训练样本）",
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        comment="音色描述（适用场景、特质等）",
    )
    default_speed: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=1.0,
        server_default="1.0",
        comment="默认语速（0.5-2.0），TTS 估时长用",
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
        comment="系统级音色标记，true 时不可被用户删除",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="UI 列表显示顺序（升序）",
    )

    __table_args__ = (
        Index("ix_voice_packs_provider_lang", "provider", "language_code"),
    )


class TtsCache(Base, TimestampMixin):
    """TTS 输出 hash 缓存：避免相同 (text, voice_pack_id, speed) 三元组重复合成（D15）。

    cache_key 是 sha256(f"{text}|{voice_pack_id}|{speed:.3f}")，由
    `app.core.contracts.tts.TtsCacheKey.to_hash()` 统一产出；命中后通过
    audio_file_id 直接复用既有 FileItem 的 minio 对象。
    """

    __tablename__ = "tts_cache"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="自增主键",
    )
    cache_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
        comment="(text, voice_pack_id, speed) 的 sha256 hash",
    )
    voice_pack_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("voice_packs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所用音色包",
    )
    text_preview: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
        server_default="",
        comment="原文前 255 字符（仅供调试，hash 才是命中依据）",
    )
    speed: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=1.0,
        server_default="1.0",
        comment="合成时的语速参数",
    )
    audio_file_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="合成结果音频 FileItem ID",
    )
    duration_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="音频时长毫秒（合成时回写）",
    )
    word_timestamps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="字级时间戳 [{text, begin_ms, end_ms}]",
    )
    hit_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="累计命中次数（运营 metrics）",
    )


__all__ = ["VoicePack", "TtsCache"]
