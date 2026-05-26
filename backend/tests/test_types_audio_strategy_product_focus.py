"""Tests for AudioStrategy / ProductFocusLevel enums (P3 W16).

确保两个新枚举字符串值与 contracts/story.py 的 Literal 严格对齐：
- AudioStrategy: silent_with_tts / keep_native (Decision D)
- ProductFocusLevel: subtle / functional / hero / none (Decision H)
"""
from __future__ import annotations

from app.models.types import AudioStrategy, ProductFocusLevel


def test_audio_strategy_values() -> None:
    """AudioStrategy 应包含 silent_with_tts 与 keep_native 两个值。"""
    assert AudioStrategy.silent_with_tts.value == "silent_with_tts"
    assert AudioStrategy.keep_native.value == "keep_native"


def test_audio_strategy_roundtrip() -> None:
    """AudioStrategy(str) 必须能从字符串回构造（对应 DB column 写回）。"""
    assert AudioStrategy("silent_with_tts") is AudioStrategy.silent_with_tts
    assert AudioStrategy("keep_native") is AudioStrategy.keep_native


def test_product_focus_level_matches_contract_literal() -> None:
    """ProductFocusLevel 字符串集合必须与 contracts/story.py 的 Literal 完全一致。"""
    expected = {"subtle", "functional", "hero", "none"}
    actual = {member.value for member in ProductFocusLevel}
    assert actual == expected


def test_product_focus_level_roundtrip() -> None:
    """ProductFocusLevel(str) 必须能从字符串回构造。"""
    assert ProductFocusLevel("subtle") is ProductFocusLevel.subtle
    assert ProductFocusLevel("functional") is ProductFocusLevel.functional
    assert ProductFocusLevel("hero") is ProductFocusLevel.hero
    assert ProductFocusLevel("none") is ProductFocusLevel.none


def test_enums_are_str_subclass() -> None:
    """两个枚举都应为 str 子类，便于 SQLAlchemy / pydantic 序列化。"""
    assert isinstance(AudioStrategy.silent_with_tts, str)
    assert isinstance(ProductFocusLevel.hero, str)
