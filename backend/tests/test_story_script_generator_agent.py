"""StoryScriptGeneratorAgent 解析与硬约束校验回归测试。

覆盖三类风险面：

1. ``format_output`` 三段式 fallback：严格 JSON → ``json-repair`` salvage；
2. ``validate_duration_drift`` / ``validate_brand_mention_cap`` 硬校验语义；
3. 异步入口 ``a_generate_script`` 在 LLM 输出之后触发上述校验，避免下游
   消费到不符合业务约束的脚本；
4. 来自 ``StoryScript`` / ``Shot`` 的 Pydantic schema 边界（镜头数 / 单镜
   时长）的负向校验。
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ValidationError

from app.chains.agents.commerce.story_script_generator_agent import (
    StoryScriptGeneratorAgent,
)
from app.core.contracts.story import Shot, StoryGenerationVars, StoryScript


class _MockChatModel(BaseChatModel):
    """最小可用的 BaseChatModel 实现：返回固定字符串响应。

    存在原因：
        StoryScriptGeneratorAgent 通过 AgentBase 的 ``aextract`` 调用模型，
        测试需要不依赖任何外部 LLM 即可断言解析与校验逻辑。
        ``with_structured_output`` 在 BaseChatModel 默认实现中抛
        ``NotImplementedError``，由 AgentBase 捕获后回退到原始字符串解析路径，
        使该 mock 自然适配现有 chain 构建逻辑。
    """

    response_text: str = ""

    @property
    def _llm_type(self) -> str:  # pragma: no cover - 标识方法，无业务逻辑
        return "mock-chat-model"

    def _generate(  # type: ignore[override]
        self,
        messages: Any,
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        message = AIMessage(content=self.response_text)
        return ChatResult(generations=[ChatGeneration(message=message)])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_shot(
    *,
    shot_id: str,
    duration_sec: float,
    product_focus_level: Literal["subtle", "functional", "hero", "none"] = "none",
    is_brand_mention: bool = False,
    is_punchline: bool = False,
) -> Shot:
    """构造测试用 Shot，仅暴露关键差异参数，其它字段使用稳定默认值。"""
    return Shot(
        id=shot_id,
        duration_sec=duration_sec,
        function="generic",
        shot_type="medium",
        camera_angle="eye_level",
        camera_movement="static",
        dialog="测试对白",
        narration=None,
        product_focus_level=product_focus_level,
        is_punchline=is_punchline,
        is_brand_mention=is_brand_mention,
        notes=None,
    )


def _make_script(
    *,
    shots: list[Shot] | None = None,
    total_duration_sec: float = 60.0,
    total_shots: int | None = None,
    formula_id: str = "dramatic_reversal",
    brand_mention_count: int = 0,
) -> StoryScript:
    """构造测试用 StoryScript，shots 默认是 4 镜 × 15s = 60s 的合规脚本。"""
    if shots is None:
        shots = [
            _make_shot(shot_id="shot_001", duration_sec=15, product_focus_level="subtle"),
            _make_shot(
                shot_id="shot_002",
                duration_sec=15,
                product_focus_level="functional",
                is_brand_mention=True,
            ),
            _make_shot(
                shot_id="shot_003",
                duration_sec=15,
                product_focus_level="hero",
                is_punchline=True,
                is_brand_mention=True,
            ),
            _make_shot(shot_id="shot_004", duration_sec=15),
        ]
    return StoryScript(
        total_duration_sec=total_duration_sec,
        total_shots=total_shots if total_shots is not None else len(shots),
        formula_id=formula_id,
        shots=shots,
        opening_hook="你试过这个吗",
        cta_text="点击购物车下单 · Vitamin C Serum",
        brand_mention_count=brand_mention_count,
    )


def _make_vars(target_duration_sec: int = 60) -> StoryGenerationVars:
    """构造测试用 StoryGenerationVars，所有 dict 字段填稳定占位结构。"""
    return StoryGenerationVars(
        formula={"id": "dramatic_reversal", "beats": ["hook", "reveal", "cta"]},
        product={
            "name": "Vitamin C Serum",
            "brand": "Acme",
            "category": "beauty",
        },
        audience={"persona": "office_worker", "pain": "dull_skin"},
        archetype="sage",
        tone_grid={"formality": 0.3, "energy": 0.7},
        target_duration_sec=target_duration_sec,
        platform="douyin",
    )


# ---------------------------------------------------------------------------
# 1. End-to-end via mock chat model
# ---------------------------------------------------------------------------


def test_generate_script_returns_valid_pydantic() -> None:
    """mock 返回 4 镜 60s 脚本，``a_generate_script`` 应得到有效 StoryScript。"""
    canned = _make_script(brand_mention_count=2).model_dump_json()
    agent = StoryScriptGeneratorAgent(_MockChatModel(response_text=canned))

    result = asyncio.run(agent.a_generate_script(vars=_make_vars(60)))

    assert isinstance(result, StoryScript)
    assert result.total_shots == 4
    assert sum(s.duration_sec for s in result.shots) == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# 2. format_output —— strict path
# ---------------------------------------------------------------------------


def test_format_output_strict_path_works_for_clean_json() -> None:
    """干净 JSON 直接走 ``model_validate_json`` 严格路径，无需 json-repair。"""
    canned = _make_script(brand_mention_count=2).model_dump_json()
    agent = StoryScriptGeneratorAgent(_MockChatModel(response_text=canned))

    result = agent.format_output(canned)

    assert isinstance(result, StoryScript)
    assert result.formula_id == "dramatic_reversal"


# ---------------------------------------------------------------------------
# 3-5. format_output —— json-repair salvage paths
# ---------------------------------------------------------------------------


def test_format_output_falls_back_to_json_repair_on_unquoted_keys() -> None:
    """未加引号的对象键应被 json-repair 修正后再校验。"""
    base = _make_script(brand_mention_count=2).model_dump()
    # 制造非法 JSON：手动去除 total_duration_sec 的双引号。
    raw = (
        f'{{total_duration_sec: {base["total_duration_sec"]}, '
        f'total_shots: {base["total_shots"]}, '
        f'formula_id: "{base["formula_id"]}", '
        f'shots: {_shots_as_json(base["shots"])}, '
        f'opening_hook: "{base["opening_hook"]}", '
        f'cta_text: "{base["cta_text"]}", '
        f'brand_mention_count: {base["brand_mention_count"]}}}'
    )
    agent = StoryScriptGeneratorAgent(_MockChatModel(response_text=raw))

    result = agent.format_output(raw)

    assert isinstance(result, StoryScript)


def test_format_output_falls_back_to_json_repair_on_trailing_comma() -> None:
    """末尾多余逗号应被 json-repair 修正后再校验。"""
    canned = _make_script(brand_mention_count=2).model_dump_json()
    # 在最后一个属性后插入尾逗号：替换末尾 `}` -> `,}`。
    raw = canned[:-1] + ",}"
    agent = StoryScriptGeneratorAgent(_MockChatModel(response_text=raw))

    result = agent.format_output(raw)

    assert isinstance(result, StoryScript)


def test_format_output_falls_back_to_json_repair_on_missing_brace() -> None:
    """末尾缺右括号的截断 JSON 应被 json-repair 自动闭合后再校验。"""
    canned = _make_script(brand_mention_count=2).model_dump_json()
    # 模拟 LLM 输出截断：去掉末尾的右括号。
    raw = canned[:-1]
    agent = StoryScriptGeneratorAgent(_MockChatModel(response_text=raw))

    result = agent.format_output(raw)

    assert isinstance(result, StoryScript)
    assert result.total_shots == 4


# ---------------------------------------------------------------------------
# 6-7. validate_duration_drift
# ---------------------------------------------------------------------------


def test_validate_duration_drift_within_10_percent_passes() -> None:
    """target=60s 且 actual=66s（漂移 10%）应恰好通过校验。"""
    shots = [
        _make_shot(shot_id="shot_001", duration_sec=20),
        _make_shot(shot_id="shot_002", duration_sec=20),
        _make_shot(shot_id="shot_003", duration_sec=20),
        _make_shot(shot_id="shot_004", duration_sec=6),
    ]
    script = _make_script(shots=shots, total_duration_sec=66.0)

    StoryScriptGeneratorAgent.validate_duration_drift(script, target_duration_sec=60)


def test_validate_duration_drift_above_10_percent_raises() -> None:
    """target=60s 且 actual=70s（漂移 16.7%）应抛 ValueError。"""
    shots = [
        _make_shot(shot_id="shot_001", duration_sec=20),
        _make_shot(shot_id="shot_002", duration_sec=20),
        _make_shot(shot_id="shot_003", duration_sec=20),
        _make_shot(shot_id="shot_004", duration_sec=10),
    ]
    script = _make_script(shots=shots, total_duration_sec=70.0)

    with pytest.raises(ValueError, match="duration drift"):
        StoryScriptGeneratorAgent.validate_duration_drift(
            script, target_duration_sec=60
        )


# ---------------------------------------------------------------------------
# 8-10. validate_brand_mention_cap
# ---------------------------------------------------------------------------


def test_validate_brand_mention_cap_60s_with_2_mentions_passes() -> None:
    """60s 脚本允许最多 2 次品牌口播——恰好 2 次应通过。"""
    shots = [
        _make_shot(shot_id="shot_001", duration_sec=20, is_brand_mention=True),
        _make_shot(shot_id="shot_002", duration_sec=20, is_brand_mention=True),
        _make_shot(shot_id="shot_003", duration_sec=20),
    ]
    script = _make_script(shots=shots, total_duration_sec=60.0, brand_mention_count=2)

    StoryScriptGeneratorAgent.validate_brand_mention_cap(
        script, target_duration_sec=60
    )


def test_validate_brand_mention_cap_60s_with_3_mentions_raises() -> None:
    """60s 脚本超过 2 次品牌口播应抛 ValueError。"""
    shots = [
        _make_shot(shot_id="shot_001", duration_sec=20, is_brand_mention=True),
        _make_shot(shot_id="shot_002", duration_sec=20, is_brand_mention=True),
        _make_shot(shot_id="shot_003", duration_sec=20, is_brand_mention=True),
    ]
    script = _make_script(shots=shots, total_duration_sec=60.0, brand_mention_count=3)

    with pytest.raises(ValueError, match="brand_mention_count"):
        StoryScriptGeneratorAgent.validate_brand_mention_cap(
            script, target_duration_sec=60
        )


def test_validate_brand_mention_cap_scales_for_120s() -> None:
    """120s 脚本上限应按比例放宽到 4，5 次仍超额。"""
    base_shots = [
        _make_shot(shot_id="shot_001", duration_sec=20, is_brand_mention=True),
        _make_shot(shot_id="shot_002", duration_sec=20, is_brand_mention=True),
        _make_shot(shot_id="shot_003", duration_sec=20, is_brand_mention=True),
        _make_shot(shot_id="shot_004", duration_sec=20, is_brand_mention=True),
        _make_shot(shot_id="shot_005", duration_sec=20),
        _make_shot(shot_id="shot_006", duration_sec=20),
    ]
    pass_script = _make_script(
        shots=base_shots, total_duration_sec=120.0, brand_mention_count=4
    )

    # 4 次品牌口播在 120s 上限内（cap=round(2*120/60)=4），应通过。
    StoryScriptGeneratorAgent.validate_brand_mention_cap(
        pass_script, target_duration_sec=120
    )

    # 第 5 次会越过上限——把 shot_005 标为品牌口播即可。
    fail_shots = list(base_shots)
    fail_shots[4] = _make_shot(
        shot_id="shot_005", duration_sec=20, is_brand_mention=True
    )
    fail_script = _make_script(
        shots=fail_shots, total_duration_sec=120.0, brand_mention_count=5
    )
    with pytest.raises(ValueError, match="brand_mention_count"):
        StoryScriptGeneratorAgent.validate_brand_mention_cap(
            fail_script, target_duration_sec=120
        )


# ---------------------------------------------------------------------------
# 11. a_generate_script triggers validators after LLM extraction
# ---------------------------------------------------------------------------


def test_a_generate_script_invokes_validators_post_extraction() -> None:
    """LLM 返回的脚本若时长漂移过大，``a_generate_script`` 应在返回前抛错。"""
    bad_shots = [
        _make_shot(shot_id="shot_001", duration_sec=20),
        _make_shot(shot_id="shot_002", duration_sec=20),
        _make_shot(shot_id="shot_003", duration_sec=20),
        _make_shot(shot_id="shot_004", duration_sec=20),
    ]
    bad_script = _make_script(shots=bad_shots, total_duration_sec=80.0)
    canned = bad_script.model_dump_json()
    agent = StoryScriptGeneratorAgent(_MockChatModel(response_text=canned))

    with pytest.raises(ValueError, match="duration drift"):
        asyncio.run(agent.a_generate_script(vars=_make_vars(60)))


# ---------------------------------------------------------------------------
# 12. structured output method wiring
# ---------------------------------------------------------------------------


def test_agent_uses_json_schema_method() -> None:
    """构造函数应将 structured output method 固定为 ``json_schema`` (D5)。"""
    agent = StoryScriptGeneratorAgent(_MockChatModel(response_text="{}"))

    # AgentBase 把方法存到 _structured_output_method；属性名是稳定 API。
    assert agent._structured_output_method == "json_schema"  # noqa: SLF001


# ---------------------------------------------------------------------------
# 13-16. Pydantic schema constraints (negative cases)
# ---------------------------------------------------------------------------


def test_shot_count_below_3_rejected_by_pydantic_schema() -> None:
    """``StoryScript.shots`` ``min_length=3`` 校验：2 镜直接拒绝。"""
    shots = [
        _make_shot(shot_id="shot_001", duration_sec=20),
        _make_shot(shot_id="shot_002", duration_sec=20),
    ]
    with pytest.raises(ValidationError):
        StoryScript(
            total_duration_sec=40,
            total_shots=2,
            formula_id="f1",
            shots=shots,
            opening_hook="hi",
            cta_text="buy",
            brand_mention_count=0,
        )


def test_shot_count_above_30_rejected_by_pydantic_schema() -> None:
    """``StoryScript.shots`` ``max_length=30`` 校验：31 镜直接拒绝。"""
    shots = [
        _make_shot(shot_id=f"shot_{i:03d}", duration_sec=2)
        for i in range(1, 32)
    ]
    with pytest.raises(ValidationError):
        StoryScript(
            total_duration_sec=62,
            total_shots=31,
            formula_id="f1",
            shots=shots,
            opening_hook="hi",
            cta_text="buy",
            brand_mention_count=0,
        )


def test_shot_duration_below_2_rejected_by_pydantic_schema() -> None:
    """``Shot.duration_sec`` ``ge=2`` 校验：1.5s 直接拒绝。"""
    with pytest.raises(ValidationError):
        _make_shot(shot_id="shot_001", duration_sec=1.5)


def test_shot_duration_above_20_rejected_by_pydantic_schema() -> None:
    """``Shot.duration_sec`` ``le=20`` 校验：21s 直接拒绝。"""
    with pytest.raises(ValidationError):
        _make_shot(shot_id="shot_001", duration_sec=21)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _shots_as_json(shots: list[dict[str, Any]]) -> str:
    """把 list[Shot dict] 序列化为可拼接的 JSON 数组字符串。

    ``json.dumps`` 在非 ASCII 文本上默认会做 unicode 转义，这里允许保留中文，
    以便测试用例语义直观可读。
    """
    import json  # pylint: disable=import-outside-toplevel

    return json.dumps(shots, ensure_ascii=False)
