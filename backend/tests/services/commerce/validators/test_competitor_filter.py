"""Competitor filter 单元测试。

覆盖：
- 精确命中竞品全名
- ASCII word boundary 命中（"Apple" 匹配 "Apple Pie"）
- ASCII word boundary 不误命中子串（"Apple" 不匹配 "pineapple"）
- 干净文本返回空 issues
- 中文竞品名走子串匹配
- 大小写不敏感
- 空 competitor 列表
"""

from __future__ import annotations

import pytest

from app.services.commerce.validators.competitor_filter import (
    build_competitor_validator,
    find_competitor_mentions,
)


def test_filter_detects_exact_competitor_name() -> None:
    """竞品名以独立词形式出现时应被命中。"""

    hits = find_competitor_mentions(
        "Try BrandX today for the best results.",
        ["BrandX"],
    )
    assert "BrandX" in hits


def test_filter_detects_word_boundary_match() -> None:
    """ASCII 竞品名出现在词边界时应命中（"Apple" 匹配 "Apple Pie"）。"""

    hits = find_competitor_mentions("I love Apple Pie.", ["Apple"])
    assert "Apple" in hits


def test_filter_does_not_false_positive_substring() -> None:
    """ASCII 竞品名不应误匹配嵌入子串（"Apple" 不匹配 "pineapple"）。"""

    hits = find_competitor_mentions(
        "I love pineapple smoothie and grappling.",
        ["Apple", "rap"],
    )
    assert hits == []


def test_filter_returns_empty_for_clean_text() -> None:
    """干净文本应返回空列表，且 validator 也返回空 issues。"""

    hits = find_competitor_mentions("This is a clean script.", ["BrandX", "Apple"])
    assert hits == []

    validator = build_competitor_validator(["BrandX", "Apple"])
    assert validator("This is a clean script.") == []


def test_filter_matches_chinese_competitor_substring() -> None:
    """中文竞品名走纯子串匹配（CJK 无 word boundary 概念）。"""

    hits = find_competitor_mentions("这款比小蓝瓶强得多。", ["小蓝瓶"])
    assert "小蓝瓶" in hits


def test_filter_is_case_insensitive_for_ascii() -> None:
    """ASCII 竞品名应忽略大小写。"""

    hits = find_competitor_mentions("Try brandx today!", ["BrandX"])
    assert "BrandX" in hits


def test_filter_handles_empty_inputs() -> None:
    """空 competitors / 空文本均应返回空。"""

    assert find_competitor_mentions("", ["BrandX"]) == []
    assert find_competitor_mentions("BrandX is everywhere", []) == []
    assert find_competitor_mentions("", []) == []


def test_validator_returns_issue_when_match_found() -> None:
    """validator 命中时应返回非空 issue 列表，并提及命中名称。"""

    validator = build_competitor_validator(["BrandX"])
    issues = validator("Try BrandX today.")
    assert issues, "validator 应在命中竞品时返回非空 issues"
    joined = " ".join(issues)
    assert "BrandX" in joined


@pytest.mark.parametrize("text", ["", None])
def test_validator_handles_empty_text(text: str | None) -> None:
    """validator 对空文本应直接返回空 issues。"""

    validator = build_competitor_validator(["BrandX"])
    assert validator(text or "") == []
