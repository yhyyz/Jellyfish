"""ASS 字幕渲染纯函数 + 句子切分策略（P3 W18 T18-5/T18-7 引入）。

为什么存在：
    把"word_timestamps + SubtitleStyle → .ass 文件文本"这一段纯计算逻辑独立出来：

    1. ``shot_subtitle_render_worker`` 调本模块产出 ASS 文本，再上传 minio；
    2. 单测可以脱离 DB / minio / 任务系统直接断言 ASS 输出（snapshot 测试）；
    3. 未来 srt / vtt 渲染器复用同一份 cue 切分结果，只需替换最终 emit 函数。

做什么：
    - ``split_words_into_cues(words, language_code, max_chars_per_cue,
      min_cue_ms, max_cue_ms)``：把字级时间戳列表切分成多条字幕 cue
      （每条 cue 对应屏幕上一段独立显示的字幕，cue 内部用 ``\\kf`` 逐词高亮）。
    - ``render_ass(style, cues)``：把 SubtitleStyle + cue 列表拼成完整 .ass
      文件文本（含 ``[Script Info]`` / ``[V4+ Styles]`` / ``[Events]`` 三段）。
    - ``format_ass_time(ms)``：毫秒 → ``H:MM:SS.cc`` ASS 时间格式（百分秒精度）。

句子切分策略（W18 T18-7）：
    - 中文：单句字符数 ≤ 15，遇 ``。！？…`` 等强标点优先切；
    - 英文：单句单词数 ≤ 7（按空格切），遇 ``.!?`` 强标点优先切；
    - cue 时长 1.8s ≤ duration ≤ 3.0s：超过 3s 会强制切成两条 cue；
    - 最少 0.5s（≤ 0.5s 的 cue 与下一段合并，避免一闪而过）；
    - 4-7 cps（chars per second）：以最大 cps 反推单条 cue 容纳上限。

    注：本模块不做"≤ 2 行"换行处理——libass 默认 ``WrapStyle=2`` 不自动换行，
    超长 cue 视觉上由用户在 SubtitleStyle.font_size + margin 上调整。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.models.subtitle import SubtitleStyle
from app.models.types import SubtitleAlignment


# ---------------------------------------------------------------------------
# 常量与字符判定
# ---------------------------------------------------------------------------


#: 默认单句字符数上限（中文场景）。
DEFAULT_MAX_CHARS_ZH: int = 15

#: 默认单句单词数上限（英文场景）。
DEFAULT_MAX_WORDS_EN: int = 7

#: 默认单条 cue 最短时长（毫秒）；< 此值的 cue 会与下一条合并。
DEFAULT_MIN_CUE_MS: int = 500

#: 默认单条 cue 最长时长（毫秒）；> 此值会强制切成两条。
DEFAULT_MAX_CUE_MS: int = 3000

#: 中文强切分标点（句号 / 感叹号 / 问号 / 省略号 / 分号 / 冒号）。
_ZH_HARD_PUNCT: frozenset[str] = frozenset("。！？…；：!?;:")

#: 英文强切分标点。
_EN_HARD_PUNCT: frozenset[str] = frozenset(".!?;:")


def _is_cjk(char: str) -> bool:
    """判断单字符是否落在 CJK 区段（U+4E00–U+9FFF），用于决定按字数还是按词数切分。"""

    return bool(char) and "\u4e00" <= char[0] <= "\u9fff"


# ---------------------------------------------------------------------------
# Cue 数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Word:
    """字级时间戳元组：(text, begin_ms, end_ms)，渲染层不可变拷贝。"""

    text: str
    begin_ms: int
    end_ms: int


@dataclass(frozen=True)
class SubtitleCue:
    """单条字幕 cue：屏幕上一次完整显示的最小单位。

    ``words`` 是 cue 内部的字级时间戳序列，渲染时用 ``\\kf<dur>`` 逐词高亮。
    ``begin_ms`` / ``end_ms`` 是 cue 整体的起止时刻，等同于 ``words[0].begin_ms``
    / ``words[-1].end_ms``。
    """

    begin_ms: int
    end_ms: int
    words: tuple[_Word, ...]

    @property
    def text(self) -> str:
        """拼接 cue 内所有字符（不含 karaoke override），便于日志/snapshot 比对。"""

        return "".join(w.text for w in self.words)


# ---------------------------------------------------------------------------
# 切分逻辑
# ---------------------------------------------------------------------------


def _normalize_words(raw: Iterable[dict[str, object]]) -> list[_Word]:
    """把 ``run_args['word_timestamps']`` 反序列化结果规范化为 ``_Word`` 列表。

    容忍：缺失 begin_ms/end_ms 的项跳过；text 为空 / None 的项跳过；
    end_ms < begin_ms 的项强制对齐到 begin_ms（避免负时长 cue）。
    """

    out: list[_Word] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        try:
            begin = int(item.get("begin_ms") or 0)
            end = int(item.get("end_ms") or 0)
        except (TypeError, ValueError):
            continue
        if begin < 0:
            begin = 0
        if end < begin:
            end = begin
        out.append(_Word(text=text, begin_ms=begin, end_ms=end))
    return out


def _detect_language_mode(words: list[_Word]) -> str:
    """判断字级时间戳列表是 CJK 主导还是英文主导。

    样本前 64 字（按字符）即可判断；纯空文本返回 ``"en"``（默认按词切）。
    """

    sample = "".join(w.text for w in words)[:64]
    if not sample:
        return "en"
    cjk = sum(1 for c in sample if _is_cjk(c))
    return "zh" if cjk > 0 else "en"


def split_words_into_cues(
    words: Iterable[dict[str, object]],
    *,
    language_code: str = "zh-CN",
    max_chars_per_cue: int | None = None,
    min_cue_ms: int = DEFAULT_MIN_CUE_MS,
    max_cue_ms: int = DEFAULT_MAX_CUE_MS,
) -> list[SubtitleCue]:
    """把字级时间戳列表按 W18 T18-7 策略切分成屏幕级 cue 列表。

    切分顺序：
        1. 把 word 序列按强标点初步切分（中文 ``。！？…`` / 英文 ``.!?``）；
        2. 切分后单 cue 字符 / 单词数仍超出上限的，按上限再切；
        3. 时长超出 ``max_cue_ms`` 的 cue 强制平均切成两条；
        4. 时长不足 ``min_cue_ms`` 的 cue 与下一条合并（最后一条保留）。

    Args:
        words: 字级时间戳 iterable，元素需含 ``text`` / ``begin_ms`` / ``end_ms``。
        language_code: 语言代码（``zh-CN`` / ``en-US`` 等）；不显式传入则按文本
            中是否含 CJK 字符自动检测。
        max_chars_per_cue: 中文单 cue 字符上限，缺省走 ``DEFAULT_MAX_CHARS_ZH``；
            英文单 cue 词数上限固定为 ``DEFAULT_MAX_WORDS_EN``，本参数不影响英文路径。
        min_cue_ms: cue 最短时长（毫秒）；< 此值合并到下一条。
        max_cue_ms: cue 最长时长（毫秒）；> 此值强制切两条。

    Returns:
        ``list[SubtitleCue]``，按时间顺序排列；空输入返回 ``[]``。
    """

    word_list = _normalize_words(words)
    if not word_list:
        return []

    explicit_lang = (language_code or "").lower()
    if explicit_lang.startswith("zh") or explicit_lang.startswith("ja"):
        mode = "zh"
    elif explicit_lang.startswith("en"):
        mode = "en"
    else:
        mode = _detect_language_mode(word_list)

    chars_limit = (
        max_chars_per_cue if max_chars_per_cue is not None else DEFAULT_MAX_CHARS_ZH
    )
    words_limit = DEFAULT_MAX_WORDS_EN

    # Step 1 + 2：按标点 + 上限切分。
    raw_cues = _split_by_punct_and_limit(
        word_list,
        mode=mode,
        chars_limit=chars_limit,
        words_limit=words_limit,
    )

    # Step 3：超长 cue 强制对半切。
    expanded: list[list[_Word]] = []
    for cue_words in raw_cues:
        if not cue_words:
            continue
        duration = cue_words[-1].end_ms - cue_words[0].begin_ms
        if duration > max_cue_ms and len(cue_words) >= 2:
            mid = len(cue_words) // 2
            expanded.append(cue_words[:mid])
            expanded.append(cue_words[mid:])
        else:
            expanded.append(cue_words)

    # Step 4：太短的"中段" cue 前向合并到下一条；尾部短 cue 保留不强制合并，
    # 避免破坏强标点（。/.）切出的清晰句界。
    merged: list[list[_Word]] = []
    i = 0
    while i < len(expanded):
        cue_words = list(expanded[i])
        duration = cue_words[-1].end_ms - cue_words[0].begin_ms
        if duration < min_cue_ms and i + 1 < len(expanded):
            # 前向合并：把当前短 cue 拼到下一条 cue 的开头并把 i+1 重置；
            # 下一轮迭代会重新评估合并后的时长是否还需要继续向后合并。
            expanded[i + 1] = cue_words + list(expanded[i + 1])
            i += 1
            continue
        merged.append(cue_words)
        i += 1

    # 转成不可变 SubtitleCue。
    return [
        SubtitleCue(
            begin_ms=cue_words[0].begin_ms,
            end_ms=cue_words[-1].end_ms,
            words=tuple(cue_words),
        )
        for cue_words in merged
        if cue_words
    ]


def _split_by_punct_and_limit(
    words: list[_Word],
    *,
    mode: str,
    chars_limit: int,
    words_limit: int,
) -> list[list[_Word]]:
    """按标点 + 字数/词数上限初步切分。

    单趟扫描：
    - 累积当前 cue 的 word 列表 + 字符/词计数；
    - 遇到强标点立刻切（避免标点出现在下一条开头）；
    - 计数达上限立刻切；
    - 末尾未切的余量作为最后一条返回。
    """

    cues: list[list[_Word]] = []
    current: list[_Word] = []
    current_count = 0

    for word in words:
        current.append(word)
        if mode == "zh":
            current_count += sum(1 for c in word.text if not c.isspace())
        else:
            current_count += 1

        last_char = word.text[-1] if word.text else ""
        hard_punct = (
            _ZH_HARD_PUNCT if mode == "zh" else _EN_HARD_PUNCT
        )
        limit = chars_limit if mode == "zh" else words_limit

        if last_char in hard_punct or current_count >= limit:
            cues.append(current)
            current = []
            current_count = 0

    if current:
        cues.append(current)
    return cues


# ---------------------------------------------------------------------------
# ASS 渲染
# ---------------------------------------------------------------------------


_ALIGNMENT_TO_NUMPAD: dict[SubtitleAlignment, int] = {
    SubtitleAlignment.bottom_left: 1,
    SubtitleAlignment.bottom_center: 2,
    SubtitleAlignment.bottom_right: 3,
    SubtitleAlignment.middle_left: 4,
    SubtitleAlignment.middle_center: 5,
    SubtitleAlignment.middle_right: 6,
    SubtitleAlignment.top_left: 7,
    SubtitleAlignment.top_center: 8,
    SubtitleAlignment.top_right: 9,
}


def _resolve_alignment_numpad(alignment: object) -> int:
    """把 SubtitleAlignment 枚举值转 ASS numpad 1-9 整数。

    容忍 SQLAlchemy 返回字符串或 Enum 实例两种情况；缺省 ``bottom_center=2``。
    """

    if isinstance(alignment, SubtitleAlignment):
        return _ALIGNMENT_TO_NUMPAD.get(alignment, 2)
    try:
        return _ALIGNMENT_TO_NUMPAD.get(SubtitleAlignment(str(alignment)), 2)
    except ValueError:
        return 2


def format_ass_time(ms: int) -> str:
    """毫秒 → ASS 时间字符串 ``H:MM:SS.cc``（百分秒精度）。

    ASS 规范要求 1 位小时 + 2 位百分秒；本函数对 < 0 的输入按 0 处理，
    > 9:59:59.99 的输入会自然溢出（生产视频极少触及该上限）。
    """

    if ms < 0:
        ms = 0
    cs = ms // 10
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _render_cue_text_with_karaoke(cue: SubtitleCue) -> str:
    """把单条 cue 的 word 序列渲染成 ``{\\kf<dur>}<word>`` 拼接的 Dialogue Text。

    ``\\kf<dur>`` 中 ``<dur>`` 单位为百分秒（centiseconds = ms / 10）。
    cue 起始时刻文字显示为 SubtitleStyle.secondary_colour，扫光过程中
    渐变到 primary_colour，符合 TikTok / 抖音流行的 karaoke 视觉。
    """

    parts: list[str] = []
    for word in cue.words:
        duration_cs = max(1, round((word.end_ms - word.begin_ms) / 10))
        parts.append(f"{{\\kf{duration_cs}}}{word.text}")
    return "".join(parts)


def render_ass(style: SubtitleStyle, cues: list[SubtitleCue]) -> str:
    """把 SubtitleStyle + cue 列表拼成完整 ``.ass`` 文件文本。

    输出固定结构：
        - ``[Script Info]``：含 ``ScriptType`` / ``PlayResX`` / ``PlayResY`` /
          ``LayoutResX`` / ``LayoutResY`` / ``ScaledBorderAndShadow`` /
          ``YCbCr Matrix`` / ``WrapStyle``；
        - ``[V4+ Styles]``：单行 Style 行，对应 SubtitleStyle 全字段；
        - ``[Events]``：每条 cue 一行 Dialogue，Text 字段含 ``\\kf`` 逐词高亮。

    返回的字符串以 ``\\n`` 结尾，可直接 encode 为 utf-8 上传 minio；调用方
    无需追加换行。

    Args:
        style: 字幕样式 ORM 对象。
        cues: ``split_words_into_cues`` 输出的 cue 列表，可为空（产出无 Dialogue 的 .ass）。

    Returns:
        完整 .ass 文件文本（utf-8 编码安全）。
    """

    alignment_num = _resolve_alignment_numpad(style.alignment)
    bold_flag = -1 if bool(style.bold) else 0
    italic_flag = -1 if bool(style.italic) else 0

    lines: list[str] = [
        "[Script Info]",
        "; Generated by jellyfish W18 subtitle renderer",
        "ScriptType: v4.00+",
        f"PlayResX: {style.play_res_x}",
        f"PlayResY: {style.play_res_y}",
        f"LayoutResX: {style.play_res_x}",
        f"LayoutResY: {style.play_res_y}",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: None",
        "WrapStyle: 2",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding"
        ),
        (
            f"Style: Default,{style.font_family},{style.font_size},"
            f"{style.primary_colour},{style.secondary_colour},"
            f"{style.outline_colour},{style.back_colour},"
            f"{bold_flag},{italic_flag},0,0,"
            "100,100,0,0,"
            f"{int(style.border_style)},{style.outline:g},{style.shadow:g},"
            f"{alignment_num},{style.margin_l},{style.margin_r},{style.margin_v},1"
        ),
        "",
        "[Events]",
        (
            "Format: Layer, Start, End, Style, Name, "
            "MarginL, MarginR, MarginV, Effect, Text"
        ),
    ]
    for cue in cues:
        text = _render_cue_text_with_karaoke(cue)
        lines.append(
            f"Dialogue: 0,{format_ass_time(cue.begin_ms)},"
            f"{format_ass_time(cue.end_ms)},Default,,0,0,0,,{text}"
        )
    return "\n".join(lines) + "\n"


__all__ = [
    "DEFAULT_MAX_CHARS_ZH",
    "DEFAULT_MAX_CUE_MS",
    "DEFAULT_MAX_WORDS_EN",
    "DEFAULT_MIN_CUE_MS",
    "SubtitleCue",
    "format_ass_time",
    "render_ass",
    "split_words_into_cues",
]
