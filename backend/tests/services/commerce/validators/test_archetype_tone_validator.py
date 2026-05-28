"""archetype + brand-tone validator 单元测试 —— P4 W25-T2。

覆盖（≥5）：

* 没挂 brand_style_guide + archetype 也未注册时直接放行；
* banned_patterns 命中加 issue；
* required_endings 在最后一镜缺失加 issue；
* brand_persona_tagline 关键词出现时通过；
* archetype 关键词命中率低于阈值加 issue；
* 兼容 ``script_breakdown.shots[*].dialog/narration`` 形态；
* 必备结尾在 narration 中也算命中（CTA 常见走 narration）。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.commerce.validators.archetype_tone_validator import (
    ARCHETYPE_KEYWORD_BAGS,
    DEFAULT_ARCHETYPE_THRESHOLD,
    validate_archetype_tone,
)


def _make_breakdown_with_dialogues(dialogues: list[str]) -> dict[str, Any]:
    """构造 task spec 直觉形态的 ``script_breakdown.dialogues``。"""

    return {"script_breakdown": {"dialogues": list(dialogues)}}


def _make_breakdown_with_shots(shot_lines: list[tuple[str | None, str | None]]) -> dict[str, Any]:
    """构造真实持久化形态：``script_breakdown.shots[*].dialog/narration``。"""

    shots = [
        {"id": f"shot_{i:03d}", "dialog": dialog, "narration": narration}
        for i, (dialog, narration) in enumerate(shot_lines, start=1)
    ]
    return {"script_breakdown": {"shots": shots}}


def test_validator_passes_clean_variant_with_no_brand_guide() -> None:
    """无 brand_style_guide 且无注册 archetype 时应直接放行。"""

    payload = _make_breakdown_with_dialogues(
        [
            "镜一：主角看着镜头说，今天天气不错。",
            "镜二：朋友走过来，递给主角一杯咖啡。",
            "镜三：旁白：故事还在继续。",
        ]
    )
    issues = validate_archetype_tone(
        variant_payload=payload,
        brand_style_guide=None,
        product_archetype=None,
    )
    assert issues == [], f"无规范 / 无 archetype 应零 issue，实际：{issues}"


def test_validator_rejects_banned_pattern_match() -> None:
    """对白命中 banned_patterns 任一条目时应返回包含模式名的 issue。"""

    payload = _make_breakdown_with_dialogues(
        [
            "买它买它买它，全网最低价！",
            "限时秒杀，错过等一年。",
            "立即下单，结束。",
        ]
    )
    guide = {
        "forced_phrases": [],
        "banned_patterns": ["全网最低价", "限时秒杀"],
        "required_endings": [],
        "brand_persona_tagline": "",
    }
    issues = validate_archetype_tone(
        variant_payload=payload,
        brand_style_guide=guide,
        product_archetype=None,
    )
    assert issues, "命中 banned 应返回非空 issues"
    joined = " ".join(issues)
    assert "全网最低价" in joined
    assert "限时秒杀" in joined


def test_validator_rejects_missing_required_ending() -> None:
    """末镜对白都不含任一必备结尾短语时应记 issue。"""

    payload = _make_breakdown_with_shots(
        [
            ("镜一对白", None),
            ("镜二对白", None),
            ("镜三对白：故事到此为止。", None),
        ]
    )
    guide = {
        "forced_phrases": [],
        "banned_patterns": [],
        "required_endings": ["了解更多请关注", "添加客服领取试用装"],
        "brand_persona_tagline": "",
    }
    issues = validate_archetype_tone(
        variant_payload=payload,
        brand_style_guide=guide,
        product_archetype=None,
    )
    assert issues, "末镜缺失必备结尾应记 issue"
    assert any("必备结尾" in i for i in issues), f"issue 文案应提及必备结尾：{issues}"


def test_validator_passes_when_persona_keyword_present() -> None:
    """brand_persona_tagline 关键词出现在对白时该维度不应记 issue。"""

    payload = _make_breakdown_with_dialogues(
        [
            "镜一：主角扎进实验室，专业团队连夜赶工。",
            "镜二：客户拍着胸口说，专家就是不一样。",
            "镜三：了解更多请关注。",
        ]
    )
    guide = {
        "forced_phrases": [],
        "banned_patterns": [],
        "required_endings": ["了解更多请关注"],
        "brand_persona_tagline": "用专业团队为你打磨细节",
    }
    issues = validate_archetype_tone(
        variant_payload=payload,
        brand_style_guide=guide,
        # archetype 选 expert，关键词袋包含「专业」「专家」，命中率应 ≥ 阈值
        product_archetype="expert",
    )
    assert not any("tagline" in i for i in issues), (
        f"对白已含 tagline 关键词时不应再报 tagline issue，实际：{issues}"
    )


def test_validator_archetype_keyword_violation_below_threshold() -> None:
    """archetype 词袋完全未命中时（命中率 0% < 5%）应记 issue。"""

    # sage 词袋的关键词都不出现在以下中性对白
    payload = _make_breakdown_with_dialogues(
        [
            "镜一：今天阳光很好。",
            "镜二：我去买杯水。",
            "镜三：再见。",
        ]
    )
    issues = validate_archetype_tone(
        variant_payload=payload,
        brand_style_guide=None,
        product_archetype="sage",
    )
    assert issues, "命中率 0 应记 issue"
    archetype_issues = [i for i in issues if "archetype" in i and "命中率" in i]
    assert archetype_issues, f"应至少有一条 archetype 命中率 issue：{issues}"
    sage_bag = ARCHETYPE_KEYWORD_BAGS["sage"]
    # 至少包含部分推荐关键词作为 retry 提示
    assert any(any(k in i for k in sage_bag) for i in archetype_issues)


def test_validator_handles_shots_form_with_narration_ending() -> None:
    """末镜的 required_ending 出现在 narration 也应被视为命中（CTA 常用旁白）。"""

    payload = _make_breakdown_with_shots(
        [
            ("镜一对白", None),
            ("镜二对白", None),
            ("镜三对白：剧情结束。", "添加客服领取试用装"),
        ]
    )
    guide = {
        "forced_phrases": [],
        "banned_patterns": [],
        "required_endings": ["添加客服领取试用装"],
        "brand_persona_tagline": "",
    }
    issues = validate_archetype_tone(
        variant_payload=payload,
        brand_style_guide=guide,
        product_archetype=None,
    )
    assert not any("必备结尾" in i for i in issues), (
        f"末镜 narration 已含 required_ending 不应再报，实际：{issues}"
    )


def test_validator_returns_empty_when_archetype_unregistered() -> None:
    """未在词袋表注册的 archetype 应放行该维度，避免误伤新增原型。"""

    payload = _make_breakdown_with_dialogues(["镜一", "镜二", "镜三"])
    issues = validate_archetype_tone(
        variant_payload=payload,
        brand_style_guide=None,
        product_archetype="not_a_real_archetype",
    )
    assert issues == [], f"未注册 archetype 应放行，实际：{issues}"


@pytest.mark.parametrize(
    "threshold",
    [DEFAULT_ARCHETYPE_THRESHOLD, 0.0, 1.0],
)
def test_validator_threshold_is_overridable(threshold: float) -> None:
    """archetype_threshold 应可由 caller 覆盖；阈值=0 时永远通过。"""

    payload = _make_breakdown_with_dialogues(
        [
            "镜一：今天阳光很好。",
            "镜二：我去买杯水。",
            "镜三：再见。",
        ]
    )
    issues = validate_archetype_tone(
        variant_payload=payload,
        brand_style_guide=None,
        product_archetype="sage",
        archetype_threshold=threshold,
    )
    if threshold <= 0.0:
        # 阈值 0 = 命中率 0 也算 ≥ 阈值 → 放行
        assert issues == []
    else:
        # 阈值 > 0 + 命中率 0 → 必报 issue
        assert issues, f"阈值 {threshold} 应触发 issue"
