"""P3 W17 Foundation：VoicePack / TtsCache ORM + TTS 契约层测试。

覆盖目标：
- VoicePack / TtsCache ORM 类可正常 import 与实例化
- TtsCacheKey.to_hash() 行为确定性（同输入同 hash，不同 text 必不同）
- TtsRequest 字段校验（speed 范围、audio_format pattern）
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


# ---------- ORM 层 ----------


def test_voice_pack_importable_and_instantiable() -> None:
    """VoicePack 可从 app.models 导入，并能构造一个实例（不入库）。"""
    from app.models import VoicePack
    from app.models.types import VoiceGender, VoiceProvider

    pack = VoicePack(
        id="cosyvoice_v2_longxiaochun",
        name="龙小淳",
        provider=VoiceProvider.aliyun_cosyvoice.value,
        provider_voice_id="longxiaochun_v2",
        language_code="zh-CN",
        gender=VoiceGender.female.value,
        description="温暖中性女声",
        default_speed=1.0,
        is_system=True,
        sort_order=10,
    )
    assert pack.id == "cosyvoice_v2_longxiaochun"
    assert pack.name == "龙小淳"
    assert pack.is_system is True
    assert pack.default_speed == 1.0


def test_tts_cache_importable_and_instantiable() -> None:
    """TtsCache 可从 app.models 导入，并能构造一个实例（不入库）。"""
    from app.models import TtsCache

    entry = TtsCache(
        cache_key="abc123",
        voice_pack_id="cosyvoice_v2_longxiaochun",
        text_preview="你好世界",
        speed=1.0,
        audio_file_id="file_xxx",
        duration_ms=2500,
        word_timestamps=[{"text": "你好", "begin_ms": 0, "end_ms": 500}],
        hit_count=0,
    )
    assert entry.cache_key == "abc123"
    assert entry.audio_file_id == "file_xxx"
    assert entry.duration_ms == 2500
    assert entry.word_timestamps[0]["text"] == "你好"


# ---------- TtsCacheKey hash ----------


def test_tts_cache_key_hash_deterministic() -> None:
    """相同 (text, voice_pack_id, speed) 必产出相同 sha256 hash。"""
    from app.core.contracts.tts import TtsCacheKey

    k1 = TtsCacheKey(text="你好世界", voice_pack_id="vp_a", speed=1.0)
    k2 = TtsCacheKey(text="你好世界", voice_pack_id="vp_a", speed=1.0)

    h1 = k1.to_hash()
    h2 = k2.to_hash()
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_tts_cache_key_hash_differs_on_text_change() -> None:
    """文本不同 hash 必不同；voice_pack_id / speed 变化亦应改变 hash。"""
    from app.core.contracts.tts import TtsCacheKey

    base = TtsCacheKey(text="你好", voice_pack_id="vp_a", speed=1.0).to_hash()
    other_text = TtsCacheKey(text="再见", voice_pack_id="vp_a", speed=1.0).to_hash()
    other_voice = TtsCacheKey(text="你好", voice_pack_id="vp_b", speed=1.0).to_hash()
    other_speed = TtsCacheKey(text="你好", voice_pack_id="vp_a", speed=1.2).to_hash()

    assert base != other_text
    assert base != other_voice
    assert base != other_speed


# ---------- TtsRequest 字段校验 ----------


def test_tts_request_speed_range_validation() -> None:
    """speed 必须落在 [0.5, 2.0]，越界抛 ValidationError。"""
    from app.core.contracts.tts import TtsRequest

    base_kwargs = {
        "text": "你好",
        "voice_pack_id": "vp_a",
        "provider_voice_id": "longxiaochun_v2",
    }

    # 边界内 OK
    TtsRequest(**base_kwargs, speed=0.5)
    TtsRequest(**base_kwargs, speed=2.0)
    TtsRequest(**base_kwargs, speed=1.0)

    # 越界抛错
    with pytest.raises(ValidationError):
        TtsRequest(**base_kwargs, speed=0.49)
    with pytest.raises(ValidationError):
        TtsRequest(**base_kwargs, speed=2.01)


def test_tts_request_audio_format_pattern() -> None:
    """audio_format 仅允许 mp3/wav/pcm/opus，其他取值抛 ValidationError。"""
    from app.core.contracts.tts import TtsRequest

    base_kwargs = {
        "text": "你好",
        "voice_pack_id": "vp_a",
        "provider_voice_id": "longxiaochun_v2",
    }

    # 合法
    for fmt in ("mp3", "wav", "pcm", "opus"):
        TtsRequest(**base_kwargs, audio_format=fmt)

    # 非法
    with pytest.raises(ValidationError):
        TtsRequest(**base_kwargs, audio_format="jpg")


def test_types_module_exposes_new_enums() -> None:
    """types.py 暴露新增枚举与 FileUsageKind 扩展。"""
    from app.models.types import (
        FileUsageKind,
        TtsClipStatus,
        VoiceGender,
        VoiceProvider,
    )

    assert VoiceGender.male.value == "male"
    assert VoiceGender.female.value == "female"
    assert VoiceGender.neutral.value == "neutral"
    assert VoiceGender.child.value == "child"

    assert VoiceProvider.aliyun_cosyvoice.value == "aliyun_cosyvoice"
    assert VoiceProvider.openai_tts.value == "openai_tts"

    assert TtsClipStatus.pending.value == "pending"
    assert TtsClipStatus.generating.value == "generating"
    assert TtsClipStatus.ready.value == "ready"
    assert TtsClipStatus.failed.value == "failed"

    # 新增 FileUsageKind 值
    assert FileUsageKind.tts_audio.value == "tts_audio"
    assert FileUsageKind.bgm_track.value == "bgm_track"
    assert FileUsageKind.sfx_track.value == "sfx_track"
