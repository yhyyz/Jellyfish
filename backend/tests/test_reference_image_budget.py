"""ReferenceImageBudget 9 槽预算分配器测试（Decision G / W16 T16-6）。"""
from __future__ import annotations

import pytest

from app.services.studio.reference_image_budget import (
    ReferenceImageBudget,
    ReferenceImageBudgetResult,
    ReferenceImageBudgetSpec,
)


def test_empty_input_returns_all_empty_no_warnings() -> None:
    """空输入应返回三个空列表与零 warning。"""
    budget = ReferenceImageBudget()
    result = budget.apply()
    assert isinstance(result, ReferenceImageBudgetResult)
    assert result.product_refs == []
    assert result.character_refs == []
    assert result.scene_refs == []
    assert result.warnings == []
    assert result.all_refs == []


def test_under_all_caps_all_preserved() -> None:
    """所有类别都未超 cap 时应原样保留且无 warning。"""
    budget = ReferenceImageBudget()
    result = budget.apply(
        product_refs=["p1", "p2"],
        character_refs=["c1"],
        scene_refs=["s1"],
    )
    assert result.product_refs == ["p1", "p2"]
    assert result.character_refs == ["c1"]
    assert result.scene_refs == ["s1"]
    assert result.warnings == []
    assert result.all_refs == ["p1", "p2", "c1", "s1"]


def test_product_overflow_only_keeps_5_with_warning() -> None:
    """Product 超过 5 个时只保留前 5 个并产生 1 条 warning。"""
    budget = ReferenceImageBudget()
    result = budget.apply(
        product_refs=["p1", "p2", "p3", "p4", "p5", "p6", "p7"],
    )
    assert result.product_refs == ["p1", "p2", "p3", "p4", "p5"]
    assert result.character_refs == []
    assert result.scene_refs == []
    assert len(result.warnings) == 1
    assert "product" in result.warnings[0].lower()
    assert "2" in result.warnings[0]


def test_character_overflow_only_keeps_3_with_warning() -> None:
    """Character 超过 3 个时只保留前 3 个并产生 1 条 warning。"""
    budget = ReferenceImageBudget()
    result = budget.apply(
        character_refs=["c1", "c2", "c3", "c4", "c5"],
    )
    assert result.character_refs == ["c1", "c2", "c3"]
    assert len(result.warnings) == 1
    assert "character" in result.warnings[0].lower()
    assert "2" in result.warnings[0]


def test_scene_overflow_only_keeps_2_with_warning() -> None:
    """Scene 超过 2 个时只保留前 2 个并产生 1 条 warning。"""
    budget = ReferenceImageBudget()
    result = budget.apply(
        scene_refs=["s1", "s2", "s3", "s4"],
    )
    assert result.scene_refs == ["s1", "s2"]
    assert len(result.warnings) == 1
    assert "scene" in result.warnings[0].lower()
    assert "2" in result.warnings[0]


def test_all_at_cap_total_exceeds_drops_scene_first() -> None:
    """5+3+2=10 但 total_cap=9，应从最低优先级 Scene 丢 1 个。"""
    budget = ReferenceImageBudget()
    result = budget.apply(
        product_refs=["p1", "p2", "p3", "p4", "p5"],
        character_refs=["c1", "c2", "c3"],
        scene_refs=["s1", "s2"],
    )
    # 总额 9，从 scene 尾部丢 1 个
    assert result.product_refs == ["p1", "p2", "p3", "p4", "p5"]
    assert result.character_refs == ["c1", "c2", "c3"]
    assert result.scene_refs == ["s1"]
    assert len(result.all_refs) == 9
    assert len(result.warnings) >= 1
    # 应有一条提到 total / scene 的 warning
    combined = " ".join(result.warnings).lower()
    assert "total" in combined or "scene" in combined


def test_max_total_override_shrinks_to_4() -> None:
    """max_total_override=4 时，3+2+2=7 输入应被裁到总额 4，按 Scene→Character→Product 顺序丢。"""
    budget = ReferenceImageBudget()
    result = budget.apply(
        product_refs=["p1", "p2", "p3"],
        character_refs=["c1", "c2"],
        scene_refs=["s1", "s2"],
        max_total_override=4,
    )
    assert len(result.all_refs) == 4
    # Product 优先保留
    assert result.product_refs == ["p1", "p2", "p3"]
    # Character 保留 1，Scene 全丢
    assert result.character_refs == ["c1"]
    assert result.scene_refs == []
    assert len(result.warnings) >= 1


def test_order_preservation_drops_tail_not_random() -> None:
    """顺序即优先级，超额时必须丢尾部，不可乱序。"""
    budget = ReferenceImageBudget()
    result = budget.apply(
        product_refs=["a", "b", "c", "d", "e", "f", "g"],
    )
    assert result.product_refs == ["a", "b", "c", "d", "e"]
    # f 与 g 是被丢弃的尾部
    assert "f" not in result.product_refs
    assert "g" not in result.product_refs


def test_custom_spec_overrides_defaults() -> None:
    """自定义 spec 应覆盖默认槽位配额。"""
    spec = ReferenceImageBudgetSpec(
        product_slots=2,
        character_slots=1,
        scene_slots=1,
        total_cap=3,
    )
    budget = ReferenceImageBudget(spec=spec)
    result = budget.apply(
        product_refs=["p1", "p2", "p3"],
        character_refs=["c1"],
        scene_refs=["s1"],
    )
    assert len(result.all_refs) == 3
    assert result.product_refs == ["p1", "p2"]


def test_warnings_are_strings_in_list() -> None:
    """warnings 应该是字符串列表，便于直接写入任务元数据。"""
    budget = ReferenceImageBudget()
    result = budget.apply(
        product_refs=["p1"] * 8,
    )
    assert isinstance(result.warnings, list)
    for w in result.warnings:
        assert isinstance(w, str)
        assert len(w) > 0


@pytest.mark.parametrize(
    "max_override,expected_total",
    [
        (1, 1),
        (5, 5),
        (9, 9),
        (100, 9),  # spec.total_cap=9 仍生效
    ],
)
def test_max_total_override_parametrized(max_override: int, expected_total: int) -> None:
    """max_total_override 与 spec.total_cap 取较小值。"""
    budget = ReferenceImageBudget()
    result = budget.apply(
        product_refs=["p1", "p2", "p3", "p4", "p5"],
        character_refs=["c1", "c2", "c3"],
        scene_refs=["s1", "s2"],
        max_total_override=max_override,
    )
    assert len(result.all_refs) == expected_total
