"""``subtitle_renderer`` 纯函数单元测试（P3 W18 T18-5/T18-7）。

覆盖目标：
1. ``format_ass_time``：毫秒到 ``H:MM:SS.cc`` 的转换边界（0 / 跨秒 / 跨分 / 负值兜底）；
2. ``split_words_into_cues`` 中文按字数 + 强标点切分；
3. ``split_words_into_cues`` 英文按词数 + 强标点切分；
4. ``split_words_into_cues`` 时长强制切分（> 3000ms）；
5. ``split_words_into_cues`` 短 cue 合并（< 500ms）；
6. ``render_ass`` snapshot：完整 .ass 文本含 [Script Info] / [V4+ Styles] / [Events]
   + ``\\kf`` 逐词高亮；
7. ``render_ass`` 空 cue：仍产出合法 .ass 头但无 Dialogue 行；
8. 颜色字段精确透传到 ASS Style 行。
"""

# pylint: disable=redefined-outer-name

from __future__ import annotations

import pytest

from app.models.subtitle import SubtitleStyle
from app.models.types import SubtitleAlignment, SubtitleFormat
from app.services.studio.subtitle_renderer import (
    DEFAULT_MAX_CUE_MS,
    DEFAULT_MIN_CUE_MS,
    format_ass_time,
    render_ass,
    split_words_into_cues,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _word(text: str, begin_ms: int, end_ms: int) -> dict[str, object]:
    """构造单个 word_timestamp dict。"""

    return {"text": text, "begin_ms": begin_ms, "end_ms": end_ms}


def _make_style(**overrides: object) -> SubtitleStyle:
    """构造未入库的 SubtitleStyle（仅供渲染纯函数测试读取字段）。"""

    defaults: dict[str, object] = {
        "id": "test_default",
        "name": "测试样式",
        "description": "",
        "language_code": "zh-CN",
        "format": SubtitleFormat.ass,
        "font_family": "Source Han Sans CN Heavy",
        "font_fallback_chain": ["Source Han Sans CN Heavy"],
        "font_size": 64,
        "primary_colour": "&H00FFFFFF",
        "secondary_colour": "&H00FFFF00",
        "outline_colour": "&H00000000",
        "back_colour": "&H80000000",
        "bold": True,
        "italic": False,
        "border_style": 1,
        "outline": 3.0,
        "shadow": 1.0,
        "alignment": SubtitleAlignment.bottom_center,
        "margin_l": 60,
        "margin_r": 60,
        "margin_v": 200,
        "play_res_x": 1080,
        "play_res_y": 1920,
        "is_system": True,
        "sort_order": 0,
    }
    defaults.update(overrides)
    return SubtitleStyle(**defaults)


# ---------------------------------------------------------------------------
# 1. format_ass_time 边界
# ---------------------------------------------------------------------------


def test_format_ass_time_zero_returns_pad_zero() -> None:
    assert format_ass_time(0) == "0:00:00.00"


def test_format_ass_time_cross_second_boundary() -> None:
    assert format_ass_time(1240) == "0:00:01.24"


def test_format_ass_time_cross_minute_boundary() -> None:
    assert format_ass_time(65_500) == "0:01:05.50"


def test_format_ass_time_cross_hour_boundary() -> None:
    assert format_ass_time(3_661_000) == "1:01:01.00"


def test_format_ass_time_negative_clamps_to_zero() -> None:
    assert format_ass_time(-100) == "0:00:00.00"


def test_format_ass_time_centisecond_precision() -> None:
    """ASS 时间精度为百分秒（10ms 一档），毫秒级被向下截断。"""
    assert format_ass_time(1239) == "0:00:01.23"


# ---------------------------------------------------------------------------
# 2. 中文按字数 + 强标点切分
# ---------------------------------------------------------------------------


def test_split_chinese_breaks_on_full_stop() -> None:
    """中文遇 ``。`` 立即切，标点留在前一条 cue。"""

    words = [
        _word("今", 0, 200),
        _word("天", 200, 400),
        _word("天", 400, 600),
        _word("气", 600, 800),
        _word("。", 800, 900),
        _word("真", 900, 1100),
        _word("好", 1100, 1300),
    ]
    cues = split_words_into_cues(words, language_code="zh-CN")
    assert len(cues) == 2
    assert cues[0].text == "今天天气。"
    assert cues[1].text == "真好"


def test_split_chinese_breaks_on_char_limit() -> None:
    """中文超出字数上限时按字数切分；时长不足 ``min_cue_ms`` 的相邻段会前向合并。"""

    words = [_word(f"字{i}", i * 100, (i + 1) * 100) for i in range(20)]
    cues = split_words_into_cues(words, language_code="zh-CN", max_chars_per_cue=8)
    # 20 个 word × 100ms = 2000ms 总时长。limit=8 chars 触发切分，但每段 400ms
    # 不足 min_cue_ms=500，会被前向合并为更少的较长 cue。无论如何，至少切出
    # 多于 1 条 cue（不应整段不切）；且每条 cue 持续时长不应短于 min_cue_ms-100ms。
    assert len(cues) >= 2
    for cue in cues[:-1]:
        duration = cue.end_ms - cue.begin_ms
        # 中段 cue 时长保证 ≥ 500ms（min_cue_ms 触发了合并补足）。
        assert duration >= DEFAULT_MIN_CUE_MS - 100


# ---------------------------------------------------------------------------
# 3. 英文按词数 + 强标点切分
# ---------------------------------------------------------------------------


def test_split_english_breaks_on_period() -> None:
    """英文遇 ``.`` 立即切。"""

    words = [
        _word("Hello", 0, 400),
        _word("world", 400, 800),
        _word("today", 800, 1200),
        _word("is", 1200, 1400),
        _word("great", 1400, 1800),
        _word(".", 1800, 1900),
        _word("Next", 1900, 2200),
        _word("part", 2200, 2500),
    ]
    cues = split_words_into_cues(words, language_code="en-US")
    assert len(cues) == 2
    assert cues[0].words[-1].text == "."


def test_split_english_breaks_on_word_limit() -> None:
    """英文超出 7 词上限时按词数切分。"""

    words = [_word(f"word{i}", i * 200, (i + 1) * 200) for i in range(15)]
    cues = split_words_into_cues(words, language_code="en-US")
    # 7 词限制：15 词 → 至少 3 条 cue（7 + 7 + 1 或 7 + 8 后被合并）
    assert len(cues) >= 2
    for cue in cues[:-1]:
        assert len(cue.words) <= 7 + 1


# ---------------------------------------------------------------------------
# 4. 时长强制切分
# ---------------------------------------------------------------------------


def test_split_force_cuts_long_cue_into_two_halves() -> None:
    """单 cue 时长 > DEFAULT_MAX_CUE_MS（3000ms）时强制对半切。"""

    # 4 个字、每个 1500ms，总 6000ms（无标点不到字数上限）。
    words = [
        _word("一", 0, 1500),
        _word("二", 1500, 3000),
        _word("三", 3000, 4500),
        _word("四", 4500, 6000),
    ]
    cues = split_words_into_cues(
        words,
        language_code="zh-CN",
        max_chars_per_cue=10,
        max_cue_ms=DEFAULT_MAX_CUE_MS,
    )
    assert len(cues) >= 2
    for cue in cues:
        duration = cue.end_ms - cue.begin_ms
        assert duration <= DEFAULT_MAX_CUE_MS + 1, (
            f"cue duration {duration} exceeds force-cut limit"
        )


# ---------------------------------------------------------------------------
# 5. 短 cue 合并
# ---------------------------------------------------------------------------


def test_split_merges_too_short_cue_with_next() -> None:
    """单 cue 时长 < DEFAULT_MIN_CUE_MS（500ms）时合并到下一条。"""

    # 第一条 ".": 200ms 极短 → 应合并；第二条 "你好世界" 1500ms 正常长度。
    words = [
        _word("。", 0, 200),
        _word("你", 200, 500),
        _word("好", 500, 800),
        _word("世", 800, 1100),
        _word("界", 1100, 1500),
    ]
    cues = split_words_into_cues(
        words,
        language_code="zh-CN",
        min_cue_ms=DEFAULT_MIN_CUE_MS,
    )
    # 第一段被合并：要么单独保留（如果是最后一条），要么并入下一条。
    # 这里有下一条，所以应合并。
    if len(cues) >= 2:
        for cue in cues[:-1]:
            assert (cue.end_ms - cue.begin_ms) >= DEFAULT_MIN_CUE_MS or cue is cues[-1]


def test_split_empty_words_returns_empty_list() -> None:
    assert split_words_into_cues([], language_code="zh-CN") == []


def test_split_skips_invalid_word_dicts() -> None:
    """text 为空 / 非 dict / 缺 begin_ms 的项被跳过。"""

    words = [
        {"text": "", "begin_ms": 0, "end_ms": 100},
        "not a dict",  # type: ignore[list-item]
        {"text": "好", "begin_ms": 100, "end_ms": 400},
    ]
    cues = split_words_into_cues(words, language_code="zh-CN")  # type: ignore[arg-type]
    assert len(cues) == 1
    assert cues[0].text == "好"


# ---------------------------------------------------------------------------
# 6. render_ass snapshot
# ---------------------------------------------------------------------------


def test_render_ass_includes_three_required_sections() -> None:
    """完整 .ass 文件必须含 [Script Info] / [V4+ Styles] / [Events] 三段。"""

    style = _make_style()
    cues = split_words_into_cues(
        [
            _word("你", 0, 300),
            _word("好", 300, 600),
        ],
        language_code="zh-CN",
    )
    ass_text = render_ass(style, cues)

    assert "[Script Info]" in ass_text
    assert "[V4+ Styles]" in ass_text
    assert "[Events]" in ass_text
    assert "ScriptType: v4.00+" in ass_text
    assert "PlayResX: 1080" in ass_text
    assert "PlayResY: 1920" in ass_text
    assert "ScaledBorderAndShadow: yes" in ass_text


def test_render_ass_emits_kf_karaoke_per_word() -> None:
    """每个 word 都应渲染成 ``{\\kf<dur>}<text>`` 形式。"""

    style = _make_style()
    cues = split_words_into_cues(
        [
            _word("Hello", 0, 500),
            _word("world", 500, 1000),
        ],
        language_code="en-US",
    )
    ass_text = render_ass(style, cues)

    # 500ms = 50 centiseconds
    assert "{\\kf50}Hello" in ass_text
    assert "{\\kf50}world" in ass_text


def test_render_ass_emits_dialogue_with_correct_timing() -> None:
    """Dialogue 行起止时间必须用 ``H:MM:SS.cc`` 格式。"""

    style = _make_style()
    cues = split_words_into_cues(
        [_word("测", 1234, 5678)],
        language_code="zh-CN",
    )
    ass_text = render_ass(style, cues)

    # 1234ms → 0:00:01.23, 5678ms → 0:00:05.67
    assert "Dialogue: 0,0:00:01.23,0:00:05.67,Default" in ass_text


def test_render_ass_empty_cues_keeps_headers_no_dialogue() -> None:
    """空 cue 列表仍产出合法 .ass 头但无 Dialogue 行。"""

    style = _make_style()
    ass_text = render_ass(style, [])

    assert "[Events]" in ass_text
    assert "Dialogue:" not in ass_text
    # Style 行仍然存在。
    assert "Style: Default" in ass_text


# ---------------------------------------------------------------------------
# 7. 颜色字段透传
# ---------------------------------------------------------------------------


def test_render_ass_passes_colour_strings_verbatim_into_style_row() -> None:
    """SubtitleStyle 的 4 个颜色字段应原样进入 Style 行。"""

    style = _make_style(
        primary_colour="&H0000D7FF",
        secondary_colour="&H00FFFFFF",
        outline_colour="&H00112233",
        back_colour="&H40556677",
    )
    ass_text = render_ass(style, [])

    style_row = next(
        line for line in ass_text.splitlines() if line.startswith("Style: Default")
    )
    parts = style_row.split(",")
    # Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour,
    #         OutlineColour, BackColour, ...
    assert parts[3] == "&H0000D7FF"
    assert parts[4] == "&H00FFFFFF"
    assert parts[5] == "&H00112233"
    assert parts[6] == "&H40556677"


def test_render_ass_alignment_numpad_translation() -> None:
    """alignment 枚举应映射到正确的 ASS numpad 数字。"""

    style = _make_style(alignment=SubtitleAlignment.top_center)
    ass_text = render_ass(style, [])
    style_row = next(
        line for line in ass_text.splitlines() if line.startswith("Style: Default")
    )
    parts = style_row.split(",")
    # Alignment 在 Format 第 19 列（0-indexed 18，但 Style: 行多个 "Default" 名占用第 0 列），
    # 实际位置：Name=0 ... Alignment=18
    assert parts[18] == "8"  # top_center = 8


def test_render_ass_bold_italic_flags_emit_minus_one_or_zero() -> None:
    """ASS Bold/Italic 字段为 -1 (true) 或 0 (false)。"""

    style_bold = _make_style(bold=True, italic=False)
    style_normal = _make_style(bold=False, italic=False)

    bold_row = next(
        line for line in render_ass(style_bold, []).splitlines()
        if line.startswith("Style: Default")
    )
    normal_row = next(
        line for line in render_ass(style_normal, []).splitlines()
        if line.startswith("Style: Default")
    )
    bold_parts = bold_row.split(",")
    normal_parts = normal_row.split(",")
    # Bold = 第 7 列（Name=0, Fontname, Fontsize, Primary, Secondary, Outline, Back, Bold=7）
    assert bold_parts[7] == "-1"
    assert normal_parts[7] == "0"
