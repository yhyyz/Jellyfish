"""``DurationEstimator`` 单元测试（P3 W17 T17-7）。

为何存在
--------

``ChapterAvPlanner`` 的 Decision F 决策树第一步就是 ``estimate``：在没有真正
合成 TTS 之前，先按 ``(text, line_mode, voice_pack.default_speed, speed)``
四元组估算时长（毫秒）。估算误差直接决定后续 mismatch 判定与 LLM
回灌频率（参见风险 R-P3-3），因此本模块用一组黑盒断言把估算行为
钉在如下不变量上：

- 中文按 ``ZH_CHARS_PER_SEC_DIALOG=4`` / ``ZH_CHARS_PER_SEC_NARRATION=3``
  区分 dialog 与 voice_over；
- 英文按 ``EN_WORDS_PER_SEC=2``（≈ 0.5s/word）折算；
- 中英混排走平均速率，避免单语侧失真；
- ``speed`` 与 ``voice_pack.default_speed`` 直接乘到 effective_rate 上；
- 空文本返回 0ms（边界）；
- 语言检测仅看 unicode 范围，不调用任何外部依赖。
"""

# pylint: disable=redefined-outer-name

from __future__ import annotations

import pytest

from app.models.types import DialogueLineMode, VoiceGender, VoiceProvider
from app.models.voice_pack import VoicePack
from app.services.studio.chapter_av_planner import (
    EN_WORDS_PER_SEC,
    ZH_CHARS_PER_SEC_DIALOG,
    ZH_CHARS_PER_SEC_NARRATION,
    DurationEstimator,
)


# ---------------------------------------------------------------------------
# 共用 fixture
# ---------------------------------------------------------------------------


def _make_voice_pack(*, default_speed: float = 1.0) -> VoicePack:
    """构造一条最小可用的 ``VoicePack`` ORM 对象（不入库）。"""

    return VoicePack(
        id="cosyvoice_v2_test",
        name="测试音色",
        provider=VoiceProvider.aliyun_cosyvoice,
        provider_voice_id="longxiaochun_v2",
        language_code="zh-CN",
        gender=VoiceGender.female,
        description="unit-test",
        default_speed=default_speed,
        is_system=True,
        sort_order=0,
    )


# ---------------------------------------------------------------------------
# 1. 语言检测
# ---------------------------------------------------------------------------


def test_detect_language_chinese_only() -> None:
    """纯中文：返回 zh。"""

    assert DurationEstimator.detect_language("你好世界") == "zh"


def test_detect_language_english_only() -> None:
    """纯英文：返回 en。"""

    assert DurationEstimator.detect_language("hello world") == "en"


def test_detect_language_mixed() -> None:
    """中英混排：返回 mixed。"""

    assert DurationEstimator.detect_language("hello 世界") == "mixed"


# ---------------------------------------------------------------------------
# 2. 中文 dialog vs narration 速率差异
# ---------------------------------------------------------------------------


def test_estimate_zh_dialog_uses_dialog_rate() -> None:
    """``DialogueLineMode.dialogue`` 走 4 chars/sec，比 narration 快。"""

    pack = _make_voice_pack()
    text = "今天天气真好我们一起去散步吧"  # 14 个汉字
    est = DurationEstimator.estimate(
        text=text, line_mode=DialogueLineMode.dialogue, voice_pack=pack, speed=1.0
    )
    # 14 / 4 = 3.5s = 3500ms（向上取整）
    assert est.language == "zh"
    assert est.char_count == 14
    assert est.chars_per_sec == pytest.approx(ZH_CHARS_PER_SEC_DIALOG)
    # 允许 ±1ms 浮点误差
    assert 3490 <= est.estimated_ms <= 3510


def test_estimate_zh_narration_slower_than_dialog() -> None:
    """``DialogueLineMode.voice_over`` 走 3 chars/sec，更慢。"""

    pack = _make_voice_pack()
    text = "暮色四合远山如黛炊烟袅袅"  # 12 个汉字
    est_narr = DurationEstimator.estimate(
        text=text, line_mode=DialogueLineMode.voice_over, voice_pack=pack, speed=1.0
    )
    est_dial = DurationEstimator.estimate(
        text=text, line_mode=DialogueLineMode.dialogue, voice_pack=pack, speed=1.0
    )
    assert est_narr.chars_per_sec == pytest.approx(ZH_CHARS_PER_SEC_NARRATION)
    # 同一段文字，旁白时长必须严格大于对白时长（3 chars/sec < 4 chars/sec）。
    assert est_narr.estimated_ms > est_dial.estimated_ms


# ---------------------------------------------------------------------------
# 3. 英文走 word-rate
# ---------------------------------------------------------------------------


def test_estimate_english_uses_word_rate() -> None:
    """英文走 ``EN_WORDS_PER_SEC * 5``（一词约 5 字符），单语稳定可估。"""

    pack = _make_voice_pack()
    text = "hello world how are you doing today"  # 6 词
    est = DurationEstimator.estimate(
        text=text, line_mode=DialogueLineMode.dialogue, voice_pack=pack, speed=1.0
    )
    assert est.language == "en"
    # base_rate = EN_WORDS_PER_SEC * 5 = 10 chars/sec
    assert est.chars_per_sec == pytest.approx(EN_WORDS_PER_SEC * 5)


# ---------------------------------------------------------------------------
# 4. speed 与 default_speed 乘性叠加
# ---------------------------------------------------------------------------


def test_estimate_speed_doubles_throughput_halves_duration() -> None:
    """speed=2.0 应把估算时长压到 1/2。"""

    pack = _make_voice_pack(default_speed=1.0)
    text = "一二三四五六七八"  # 8 个汉字
    base = DurationEstimator.estimate(
        text=text, line_mode=DialogueLineMode.dialogue, voice_pack=pack, speed=1.0
    )
    fast = DurationEstimator.estimate(
        text=text, line_mode=DialogueLineMode.dialogue, voice_pack=pack, speed=2.0
    )
    # 浮点取整下允许 ±1ms 误差
    assert abs(fast.estimated_ms * 2 - base.estimated_ms) <= 2


def test_estimate_voice_pack_default_speed_applies_multiplicatively() -> None:
    """``voice_pack.default_speed`` 与 ``speed`` 相乘进入 effective_rate。"""

    pack_normal = _make_voice_pack(default_speed=1.0)
    pack_fast = _make_voice_pack(default_speed=2.0)
    text = "测试默认语速倍率叠加效果"  # 12 字
    est_normal = DurationEstimator.estimate(
        text=text, line_mode=DialogueLineMode.dialogue, voice_pack=pack_normal, speed=1.0
    )
    est_fast = DurationEstimator.estimate(
        text=text, line_mode=DialogueLineMode.dialogue, voice_pack=pack_fast, speed=1.0
    )
    # default_speed=2.0 应让时长压到 1/2
    assert abs(est_fast.estimated_ms * 2 - est_normal.estimated_ms) <= 2


# ---------------------------------------------------------------------------
# 5. 边界：空文本
# ---------------------------------------------------------------------------


def test_estimate_empty_text_returns_zero_ms() -> None:
    """空文本：估算时长应严格为 0，不抛除零异常。"""

    pack = _make_voice_pack()
    est = DurationEstimator.estimate(
        text="", line_mode=DialogueLineMode.dialogue, voice_pack=pack, speed=1.0
    )
    assert est.char_count == 0
    assert est.estimated_ms == 0


# ---------------------------------------------------------------------------
# 6. 中英混排：取 dialog/word-rate 的算术均值
# ---------------------------------------------------------------------------


def test_estimate_mixed_text_uses_blended_rate() -> None:
    """中英混排：返回 mixed 语言标签且产出非零时长。"""

    pack = _make_voice_pack()
    text = "今天 the demo 很赞"
    est = DurationEstimator.estimate(
        text=text, line_mode=DialogueLineMode.dialogue, voice_pack=pack, speed=1.0
    )
    assert est.language == "mixed"
    assert est.estimated_ms > 0
    # 速率应介于纯中文 dialog 速率与纯英文速率之间。
    en_rate = EN_WORDS_PER_SEC * 5
    assert min(ZH_CHARS_PER_SEC_DIALOG, en_rate) <= est.chars_per_sec <= max(
        ZH_CHARS_PER_SEC_DIALOG, en_rate
    )
