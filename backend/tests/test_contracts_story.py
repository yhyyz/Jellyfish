"""``app.core.contracts.story`` 共享 DTO 测试。

校验所有 7 个模型的：
- 正向实例化
- ``extra="forbid"`` 拒绝多余字段
- 关键约束（duration、min/max length、ge/le）
- JSON round-trip 等价性
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.contracts import (
    BrandVoice,
    ComplianceFinding,
    ComplianceReport,
    ProductExtractionResult,
    Shot,
    StoryGenerationVars,
    StoryScript,
)


def _valid_shot(shot_id: str = "shot_001", duration: float = 5.0) -> Shot:
    """构造一个合法的 ``Shot`` 实例供测试复用。"""
    return Shot(
        id=shot_id,
        duration_sec=duration,
        function="hook",
        shot_type="close_up",
        camera_angle="eye_level",
        camera_movement="static",
        dialog=None,
        narration=None,
        product_focus_level="subtle",
        is_punchline=False,
        is_brand_mention=False,
        notes=None,
    )


def _valid_story_script() -> StoryScript:
    """构造一个合法的 ``StoryScript`` 实例供测试复用。"""
    shots = [_valid_shot(f"shot_{i:03d}") for i in range(3)]
    return StoryScript(
        total_duration_sec=15.0,
        total_shots=3,
        formula_id="formula_aida",
        shots=shots,
        opening_hook="3 秒内抓住注意力",
        cta_text="立即点击购买",
        brand_mention_count=1,
    )


def _valid_product() -> ProductExtractionResult:
    """构造一个合法的 ``ProductExtractionResult`` 实例供测试复用。"""
    return ProductExtractionResult(
        name="柔顺洗发水",
        brand="JellyBrand",
        category="personal_care",
        description="温和柔顺洗发水",
        price_anchor=39.9,
        sku="SKU-001",
        selling_points=["温和", "去屑"],
        pain_points_solved=["头屑", "干枯"],
        target_audience={"age": "20-35"},
        catchphrases=["柔顺一整天"],
        competitor_names=["Brand A"],
        health_disclaimer_required=False,
    )


def _valid_finding() -> ComplianceFinding:
    """构造一个合法的 ``ComplianceFinding`` 实例供测试复用。"""
    return ComplianceFinding(
        rule_id="rule_001",
        rule_kind="banned_phrase",
        severity="warning",
        description="包含夸大宣传词",
        location="shot_001",
        suggested_fix="替换为温和表达",
    )


def _valid_report() -> ComplianceReport:
    """构造一个合法的 ``ComplianceReport`` 实例供测试复用。"""
    return ComplianceReport(
        variant_id=None,
        region="CN",
        product_category="personal_care",
        findings=[_valid_finding()],
        score=85,
        summary="整体合规，存在一处警告",
    )


def _valid_vars() -> StoryGenerationVars:
    """构造一个合法的 ``StoryGenerationVars`` 实例供测试复用。"""
    return StoryGenerationVars(
        formula={"id": "formula_aida"},
        product={"name": "柔顺洗发水"},
        audience={"age": "20-35"},
        archetype="hero",
        tone_grid={"energy": "high"},
        target_duration_sec=30,
        platform="douyin",
    )


def _valid_voice() -> BrandVoice:
    """构造一个合法的 ``BrandVoice`` 实例供测试复用。"""
    return BrandVoice(archetype="sage", tone_grid={"warmth": "medium"})


# ---------------------------------------------------------------------------
# 正向实例化
# ---------------------------------------------------------------------------


def test_shot_instantiates() -> None:
    """``Shot`` 在合法字段下可成功构造。"""
    assert _valid_shot().id == "shot_001"


def test_story_script_instantiates() -> None:
    """``StoryScript`` 在合法字段下可成功构造。"""
    script = _valid_story_script()
    assert script.total_shots == 3
    assert len(script.shots) == 3


def test_story_generation_vars_instantiates() -> None:
    """``StoryGenerationVars`` 在合法字段下可成功构造。"""
    assert _valid_vars().platform == "douyin"


def test_product_extraction_result_instantiates() -> None:
    """``ProductExtractionResult`` 在合法字段下可成功构造。"""
    assert _valid_product().name == "柔顺洗发水"


def test_compliance_finding_instantiates() -> None:
    """``ComplianceFinding`` 在合法字段下可成功构造。"""
    assert _valid_finding().rule_kind == "banned_phrase"


def test_compliance_report_instantiates() -> None:
    """``ComplianceReport`` 在合法字段下可成功构造。"""
    assert _valid_report().score == 85


def test_brand_voice_instantiates() -> None:
    """``BrandVoice`` 在合法字段下可成功构造。"""
    assert _valid_voice().archetype == "sage"


# ---------------------------------------------------------------------------
# extra="forbid" 拒绝多余字段
# ---------------------------------------------------------------------------


def test_shot_forbids_extra_fields() -> None:
    """``Shot`` 拒绝未声明的字段。"""
    payload = _valid_shot().model_dump()
    payload["unknown"] = "x"
    with pytest.raises(ValidationError):
        Shot.model_validate(payload)


def test_story_script_forbids_extra_fields() -> None:
    """``StoryScript`` 拒绝未声明的字段。"""
    payload = _valid_story_script().model_dump()
    payload["unknown"] = 1
    with pytest.raises(ValidationError):
        StoryScript.model_validate(payload)


def test_story_generation_vars_forbids_extra_fields() -> None:
    """``StoryGenerationVars`` 拒绝未声明的字段。"""
    payload = _valid_vars().model_dump()
    payload["unknown"] = 1
    with pytest.raises(ValidationError):
        StoryGenerationVars.model_validate(payload)


def test_product_extraction_result_forbids_extra_fields() -> None:
    """``ProductExtractionResult`` 拒绝未声明的字段。"""
    payload = _valid_product().model_dump()
    payload["unknown"] = 1
    with pytest.raises(ValidationError):
        ProductExtractionResult.model_validate(payload)


def test_compliance_finding_forbids_extra_fields() -> None:
    """``ComplianceFinding`` 拒绝未声明的字段。"""
    payload = _valid_finding().model_dump()
    payload["unknown"] = 1
    with pytest.raises(ValidationError):
        ComplianceFinding.model_validate(payload)


def test_compliance_report_forbids_extra_fields() -> None:
    """``ComplianceReport`` 拒绝未声明的字段。"""
    payload = _valid_report().model_dump()
    payload["unknown"] = 1
    with pytest.raises(ValidationError):
        ComplianceReport.model_validate(payload)


def test_brand_voice_forbids_extra_fields() -> None:
    """``BrandVoice`` 拒绝未声明的字段。"""
    payload = _valid_voice().model_dump()
    payload["unknown"] = 1
    with pytest.raises(ValidationError):
        BrandVoice.model_validate(payload)


# ---------------------------------------------------------------------------
# 约束校验
# ---------------------------------------------------------------------------


def test_shot_duration_below_min_raises() -> None:
    """``Shot`` 时长低于 2 秒应抛出 ``ValidationError``。"""
    with pytest.raises(ValidationError):
        _valid_shot(duration=1.0)


def test_shot_duration_above_max_raises() -> None:
    """``Shot`` 时长超过 20 秒应抛出 ``ValidationError``。"""
    with pytest.raises(ValidationError):
        _valid_shot(duration=21.0)


def test_story_script_zero_shots_raises() -> None:
    """``StoryScript`` 给定 0 个镜头应抛出 ``ValidationError``。"""
    with pytest.raises(ValidationError):
        StoryScript(
            total_duration_sec=0.0,
            total_shots=0,
            formula_id="formula_aida",
            shots=[],
            opening_hook="hook",
            cta_text="cta",
            brand_mention_count=0,
        )


def test_product_extraction_too_many_selling_points_raises() -> None:
    """``ProductExtractionResult`` 卖点超过 5 条应抛出 ``ValidationError``。"""
    with pytest.raises(ValidationError):
        ProductExtractionResult(
            name="商品",
            brand=None,
            category="other",
            description="描述",
            price_anchor=None,
            sku=None,
            selling_points=["a", "b", "c", "d", "e", "f"],
            pain_points_solved=[],
            target_audience={},
            catchphrases=[],
            competitor_names=[],
            health_disclaimer_required=False,
        )


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "factory",
    [
        _valid_shot,
        _valid_story_script,
        _valid_vars,
        _valid_product,
        _valid_finding,
        _valid_report,
        _valid_voice,
    ],
)
def test_json_round_trip(factory) -> None:
    """``model_dump_json`` -> ``model_validate_json`` 应保持等价。"""
    original = factory()
    restored = type(original).model_validate_json(original.model_dump_json())
    assert restored == original
