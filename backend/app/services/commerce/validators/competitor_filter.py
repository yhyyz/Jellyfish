"""竞品名出现检测：LLM 生成阶段的"品牌资产保险柜"硬约束 validator。

为什么存在：
    `Product.competitor_names` 列出了"严禁在剧情台词/钩子/CTA 文案
    里出现"的竞品。LLM 在生成阶段无法 100% 自觉规避，需要后置一道
    硬扫描；如果命中就把 issues 反馈给 agent 触发一次带 guidance 的
    重试（见 :mod:`app.chains.agents._retry`）。

为什么走 Aho-Corasick：
    - 单条脚本通常 200~600 字，竞品名 ≤ 20 个；纯 ``re.search`` 走 N
      次扫描在工程上完全够用，但 :mod:`pyahocorasick` 已经是项目内
      的标准多模式扫描工具（见 ``app/services/compliance/rule_engine``），
      为保持一致性同样在这里使用。
    - 同时支持 ASCII 与 CJK 竞品名。

词边界处理：
    - 纯 ASCII（仅含字母/数字/下划线）的竞品名要求 word boundary，
      避免 "Apple" 误匹配 "pineapple"。
    - 含 CJK 或其它非 ASCII 字符的竞品名（如 "小蓝瓶"）走纯子串匹配，
      因为 CJK 文本无空白分词，强加 boundary 反而漏报。

边界 / 防御性：
    - 空 ``competitor_names`` 或空文本直接返回空，匹配函数与 validator
      都不抛异常。
    - 自动机内部统一在 ``.lower()`` 文本上扫描，所以 ASCII 名匹配是
      大小写不敏感的；返回的命中名以 ``competitor_names`` 中登记的原
      始大小写呈现，便于 UI 展示与 retry guidance 引用。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

import ahocorasick


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _is_ascii_word(name: str) -> bool:
    """判断 competitor 名是否为纯 ASCII 标识符样式。

    仅当全部字符都是 ASCII 字母、数字或下划线时返回 True。这类名字
    在西文文本中应启用 word boundary 检查（"Apple" vs "pineapple"）。
    """

    if not name:
        return False
    return all(("a" <= c <= "z") or ("A" <= c <= "Z") or ("0" <= c <= "9") or c == "_" for c in name)


def _is_word_char(char: str) -> bool:
    """word boundary 用：字符是否参与 ASCII"单词"。

    与 :func:`_is_ascii_word` 一致，认为 ``[A-Za-z0-9_]`` 才是单词字符。
    其它字符（含 CJK、空白、标点）均视为 boundary。
    """

    if not char:
        return False
    return ("a" <= char <= "z") or ("A" <= char <= "Z") or ("0" <= char <= "9") or char == "_"


def _check_word_boundary(text: str, start: int, end_inclusive: int) -> bool:
    """检查 ``text[start:end_inclusive+1]`` 两侧是否为 word boundary。

    Args:
        text: 原始（lower 化后的）文本。
        start: 命中片段起点下标（含）。
        end_inclusive: 命中片段终点下标（含）。

    Returns:
        命中片段两侧均不是 word 字符，或在文本两端时返回 True。
    """

    left_ok = start <= 0 or not _is_word_char(text[start - 1])
    right_ok = end_inclusive >= len(text) - 1 or not _is_word_char(text[end_inclusive + 1])
    return left_ok and right_ok


def _build_automaton(
    names: Iterable[str],
) -> tuple[ahocorasick.Automaton, dict[str, str], dict[str, bool]]:
    """构建 AC 自动机并返回 (automaton, lower2original, lower2is_ascii)。

    去重逻辑：同一 lower 形式的多次出现，保留首次登记的原始大小写，
    避免后续命中报告里出现重复别名。
    """

    automaton = ahocorasick.Automaton()
    lower2original: dict[str, str] = {}
    lower2is_ascii: dict[str, bool] = {}
    for name in names:
        cleaned = (name or "").strip()
        if not cleaned:
            continue
        normalized = cleaned.lower()
        if normalized in lower2original:
            continue
        lower2original[normalized] = cleaned
        lower2is_ascii[normalized] = _is_ascii_word(cleaned)
        automaton.add_word(normalized, normalized)
    try:
        automaton.make_automaton()
    except (ValueError, AttributeError):
        # pyahocorasick 在没有任何 word 时偶尔会拒绝 make_automaton；
        # 忽略后保留空机，``iter()`` 会即时返回空生成器。
        pass
    return automaton, lower2original, lower2is_ascii


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------


def find_competitor_mentions(
    text: str,
    competitor_names: Iterable[str],
) -> list[str]:
    """扫描 ``text``，返回命中的竞品名（按登记原大小写、去重、保持首次出现顺序）。

    Args:
        text: 待扫描的生成文本（脚本/钩子/CTA 等任何 LLM 输出片段）。
        competitor_names: 该商品登记的竞品名列表（``Product.competitor_names``）。

    Returns:
        一个去重后的列表，列出文本中实际出现的竞品名；空列表表示干净。
    """

    if not text:
        return []
    cleaned_names = [n for n in competitor_names if n and n.strip()]
    if not cleaned_names:
        return []

    automaton, lower2original, lower2is_ascii = _build_automaton(cleaned_names)
    if not lower2original:
        return []

    normalized_text = text.lower()
    seen: set[str] = set()
    hits: list[str] = []
    for end_idx, lower_name in automaton.iter(normalized_text):
        start = end_idx - len(lower_name) + 1
        if lower2is_ascii.get(lower_name, False):
            if not _check_word_boundary(normalized_text, start, end_idx):
                continue
        original = lower2original.get(lower_name)
        if original is None or original in seen:
            continue
        seen.add(original)
        hits.append(original)
    return hits


def build_competitor_validator(
    competitor_names: Iterable[str],
) -> Callable[[str], list[str]]:
    """构造 retry helper 用的 validator：``(output_text) -> list[str]``。

    返回的 callable 在命中竞品时产出一条人类可读的 issue（包含命中名），
    供 :func:`app.chains.agents._retry.retry_with_validator` 拼接成 retry
    guidance 反馈给 agent。

    设计要点：
        - competitor_names 在闭包内**实例化为 tuple**，避免外部传入的生成
          器在第二次调用时被消费成空。
        - 单条 issue 同时列出全部命中名，让 agent 一次性了解需要剔除哪些
          关键词，减少多轮重试。
    """

    materialized = tuple(name for name in competitor_names if name and name.strip())

    def _validate(output: str) -> list[str]:
        if not output:
            return []
        if not materialized:
            return []
        hits = find_competitor_mentions(output, materialized)
        if not hits:
            return []
        joined = "、".join(hits)
        return [f"输出中包含禁止提及的竞品名：{joined}，请改用通用描述或品牌自有卖点替换。"]

    return _validate


__all__ = [
    "build_competitor_validator",
    "find_competitor_mentions",
]
