"""ArchetypeVoiceRewriterAgent 解析与结构保留校验回归测试。

覆盖三类风险面：

1. ``format_output`` 的严格 JSON 路径与 ``json-repair`` salvage 路径；
2. ``validate_structure_preserved`` / ``validate_words_to_avoid`` 硬校验语义；
3. 异步入口 ``a_rewrite_voice`` 在 LLM 输出之后触发上述校验，
   避免下游消费到结构被改动或含禁词的脚本；
4. Agent 与 ``StoryScript`` schema、``json_schema`` 输出方法等接线。
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.chains.agents.commerce.archetype_voice_rewriter_agent import (
    ARCHETYPE_REWRITE_PROMPT,
    ArchetypeVoiceRewriterAgent,
)
from app.core.contracts.story import (
    ArchetypeRewriteVars,
    Shot,
    StoryScript,
)


class _MockChatModel(BaseChatModel):
    """最小可用的 BaseChatModel 实现：返回固定字符串响应。

    存在原因：
        ArchetypeVoiceRewriterAgent 通过 AgentBase 的 ``aextract`` 调用模型，
        测试需要不依赖任何外部 LLM 即可断言解析与校验逻辑。
        ``with_structured_output`` 在 BaseChatModel 默认实现中抛
        ``NotImplementedError``，由 AgentBase 捕获后回退到原始字符串解析路径。
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
    duration_sec: float = 10,
    shot_type: str = "medium",
    camera_angle: str = "eye_level",
    camera_movement: str = "static",
    dialog: str | None = "原始对白",
    narration: str | None = None,
    product_focus_level: Literal["subtle", "functional", "hero", "none"] = "none",
    is_brand_mention: bool = False,
    is_punchline: bool = False,
) -> Shot:
    """构造测试用 Shot；仅暴露关键差异参数，其它字段使用稳定默认值。"""
    return Shot(
        id=shot_id,
        duration_sec=duration_sec,
        function="generic",
        shot_type=shot_type,
        camera_angle=camera_angle,
        camera_movement=camera_movement,
        dialog=dialog,
        narration=narration,
        product_focus_level=product_focus_level,
        is_punchline=is_punchline,
        is_brand_mention=is_brand_mention,
        notes=None,
    )


def _make_script(
    *,
    shots: list[Shot] | None = None,
    opening_hook: str = "你试过这个吗",
    cta_text: str = "点击购物车下单 · Vitamin C Serum",
    brand_mention_count: int = 1,
    formula_id: str = "dramatic_reversal",
) -> StoryScript:
    """构造测试用 StoryScript，shots 默认是 4 镜 × 15s = 60s。"""
    if shots is None:
        shots = [
            _make_shot(shot_id="shot_001", duration_sec=15, dialog="第一镜对白"),
            _make_shot(
                shot_id="shot_002",
                duration_sec=15,
                dialog="第二镜对白",
                product_focus_level="functional",
                is_brand_mention=True,
            ),
            _make_shot(
                shot_id="shot_003",
                duration_sec=15,
                dialog=None,
                narration="第三镜旁白",
            ),
            _make_shot(shot_id="shot_004", duration_sec=15, dialog="第四镜对白"),
        ]
    return StoryScript(
        total_duration_sec=sum(s.duration_sec for s in shots),
        total_shots=len(shots),
        formula_id=formula_id,
        shots=shots,
        opening_hook=opening_hook,
        cta_text=cta_text,
        brand_mention_count=brand_mention_count,
    )


def _make_vars(
    *,
    original_script: StoryScript | None = None,
    archetype: str = "sage",
    archetype_description: str = "智者人格：理性、克制、信息密度高",
    tone_grid: dict[str, int] | None = None,
    words_to_avoid: list[str] | None = None,
    preferred_vocab: list[str] | None = None,
) -> ArchetypeRewriteVars:
    """构造测试用 ``ArchetypeRewriteVars``，所有字段均提供稳定默认值。"""
    script = original_script if original_script is not None else _make_script()
    return ArchetypeRewriteVars(
        original_script=script.model_dump(),
        archetype=archetype,
        archetype_description=archetype_description,
        tone_grid=tone_grid if tone_grid is not None else {"formality": 7, "energy": 4},
        words_to_avoid=words_to_avoid if words_to_avoid is not None else [],
        preferred_vocab=preferred_vocab if preferred_vocab is not None else [],
    )


def _rewritten_clone(
    original: StoryScript,
    *,
    new_dialog: str = "改写后的对白",
    new_opening_hook: str | None = None,
    new_cta_text: str | None = None,
) -> StoryScript:
    """基于 ``original`` 复制一份脚本，仅替换文本字段，保留结构。"""
    new_shots = [
        Shot(
            id=s.id,
            duration_sec=s.duration_sec,
            function=s.function,
            shot_type=s.shot_type,
            camera_angle=s.camera_angle,
            camera_movement=s.camera_movement,
            dialog=new_dialog if s.dialog is not None else None,
            narration=("改写后的旁白" if s.narration is not None else None),
            product_focus_level=s.product_focus_level,
            is_punchline=s.is_punchline,
            is_brand_mention=s.is_brand_mention,
            notes=s.notes,
        )
        for s in original.shots
    ]
    return StoryScript(
        total_duration_sec=original.total_duration_sec,
        total_shots=original.total_shots,
        formula_id=original.formula_id,
        shots=new_shots,
        opening_hook=new_opening_hook
        if new_opening_hook is not None
        else original.opening_hook,
        cta_text=new_cta_text if new_cta_text is not None else original.cta_text,
        brand_mention_count=original.brand_mention_count,
    )


# ---------------------------------------------------------------------------
# 1. End-to-end via mock chat model
# ---------------------------------------------------------------------------


def test_a_rewrite_voice_returns_valid_storyscript() -> None:
    """mock 返回结构保留的脚本，``a_rewrite_voice`` 应得到有效 StoryScript。"""
    original = _make_script()
    rewritten = _rewritten_clone(original, new_dialog="智者风格的对白")
    canned = rewritten.model_dump_json()
    agent = ArchetypeVoiceRewriterAgent(_MockChatModel(response_text=canned))

    vars_ = _make_vars(original_script=original)
    result = asyncio.run(agent.a_rewrite_voice(vars=vars_))

    assert isinstance(result, StoryScript)
    assert len(result.shots) == len(original.shots)
    assert all(s.dialog != "原始对白" for s in result.shots if s.dialog is not None)


# ---------------------------------------------------------------------------
# 2-7. validate_structure_preserved
# ---------------------------------------------------------------------------


def test_validate_structure_preserved_passes_for_identical() -> None:
    """完全相同的脚本应通过结构保留校验。"""
    script = _make_script()
    ArchetypeVoiceRewriterAgent.validate_structure_preserved(script, script)


def test_validate_structure_preserved_raises_on_shot_count_mismatch() -> None:
    """改写后镜头数发生变化应抛错。"""
    original = _make_script()
    bad_shots = list(original.shots[:-1])  # 故意少一镜
    bad = StoryScript(
        total_duration_sec=sum(s.duration_sec for s in bad_shots),
        total_shots=len(bad_shots),
        formula_id=original.formula_id,
        shots=bad_shots,
        opening_hook=original.opening_hook,
        cta_text=original.cta_text,
        brand_mention_count=original.brand_mention_count,
    )

    with pytest.raises(ValueError, match="shot count changed"):
        ArchetypeVoiceRewriterAgent.validate_structure_preserved(original, bad)


def test_validate_structure_preserved_raises_on_id_change() -> None:
    """改写后 shot.id 被改动应抛错并指明字段。"""
    original = _make_script()
    bad = _rewritten_clone(original)
    # 复制完整 shots 列表后人为改首镜 id
    new_shots = list(bad.shots)
    new_shots[0] = Shot(
        **{**new_shots[0].model_dump(), "id": "shot_999"},
    )
    bad = StoryScript(
        **{**bad.model_dump(), "shots": [s.model_dump() for s in new_shots]}
    )

    with pytest.raises(ValueError, match="field id changed"):
        ArchetypeVoiceRewriterAgent.validate_structure_preserved(original, bad)


def test_validate_structure_preserved_raises_on_duration_change() -> None:
    """改写后 duration_sec 被改动应抛错。"""
    original = _make_script()
    new_shots = [s.model_copy(update={}) for s in original.shots]
    new_shots[1] = new_shots[1].model_copy(update={"duration_sec": 17.0})
    bad = original.model_copy(update={"shots": new_shots})

    with pytest.raises(ValueError, match="field duration_sec changed"):
        ArchetypeVoiceRewriterAgent.validate_structure_preserved(original, bad)


def test_validate_structure_preserved_raises_on_shot_type_change() -> None:
    """改写后 shot_type 被改动应抛错。"""
    original = _make_script()
    new_shots = [s.model_copy(update={}) for s in original.shots]
    new_shots[0] = new_shots[0].model_copy(update={"shot_type": "wide"})
    bad = original.model_copy(update={"shots": new_shots})

    with pytest.raises(ValueError, match="field shot_type changed"):
        ArchetypeVoiceRewriterAgent.validate_structure_preserved(original, bad)


def test_validate_structure_preserved_raises_on_camera_angle_change() -> None:
    """改写后 camera_angle 被改动应抛错。"""
    original = _make_script()
    new_shots = [s.model_copy(update={}) for s in original.shots]
    new_shots[2] = new_shots[2].model_copy(update={"camera_angle": "high_angle"})
    bad = original.model_copy(update={"shots": new_shots})

    with pytest.raises(ValueError, match="field camera_angle changed"):
        ArchetypeVoiceRewriterAgent.validate_structure_preserved(original, bad)


def test_validate_structure_preserved_raises_on_camera_movement_change() -> None:
    """改写后 camera_movement 被改动应抛错（覆盖五项保留字段中的最后一项）。"""
    original = _make_script()
    new_shots = [s.model_copy(update={}) for s in original.shots]
    new_shots[3] = new_shots[3].model_copy(update={"camera_movement": "push_in"})
    bad = original.model_copy(update={"shots": new_shots})

    with pytest.raises(ValueError, match="field camera_movement changed"):
        ArchetypeVoiceRewriterAgent.validate_structure_preserved(original, bad)


def test_validate_structure_preserved_raises_on_brand_mention_count_change() -> None:
    """改写后品牌口播镜数发生变化应抛错。"""
    original = _make_script()
    new_shots = [s.model_copy(update={}) for s in original.shots]
    # 把原本不口播的 shot_001 改成口播，导致总数从 1 变 2。
    new_shots[0] = new_shots[0].model_copy(update={"is_brand_mention": True})
    bad = original.model_copy(update={"shots": new_shots})

    with pytest.raises(ValueError, match="brand_mention_count changed"):
        ArchetypeVoiceRewriterAgent.validate_structure_preserved(original, bad)


# ---------------------------------------------------------------------------
# 8-9. validate_words_to_avoid
# ---------------------------------------------------------------------------


def test_validate_words_to_avoid_passes_when_clean() -> None:
    """禁词列表与脚本完全无交集时应直接通过。"""
    script = _make_script(opening_hook="今天聊点干货", cta_text="点击下单试试")
    ArchetypeVoiceRewriterAgent.validate_words_to_avoid(
        script,
        words_to_avoid=["最强", "保证治愈"],
    )


def test_validate_words_to_avoid_passes_for_empty_list() -> None:
    """空禁词列表应直接放行（短路返回）。"""
    script = _make_script(opening_hook="任意文案")
    ArchetypeVoiceRewriterAgent.validate_words_to_avoid(script, words_to_avoid=[])


def test_validate_words_to_avoid_raises_on_violation() -> None:
    """禁词命中任意文本字段应抛错并列出全部命中词。"""
    bad_script = _make_script(
        opening_hook="今天给你最强体验",
        cta_text="点击下单",
    )
    with pytest.raises(ValueError, match="words_to_avoid violated"):
        ArchetypeVoiceRewriterAgent.validate_words_to_avoid(
            bad_script,
            words_to_avoid=["最强"],
        )


# ---------------------------------------------------------------------------
# 10. a_rewrite_voice triggers validators after LLM extraction
# ---------------------------------------------------------------------------


def test_a_rewrite_voice_invokes_validators_post_extraction() -> None:
    """LLM 返回的脚本若结构被破坏，``a_rewrite_voice`` 应在返回前抛错。"""
    original = _make_script()
    bad_shots = list(original.shots[:-1])  # 故意少一镜，结构破坏
    bad = StoryScript(
        total_duration_sec=sum(s.duration_sec for s in bad_shots),
        total_shots=len(bad_shots),
        formula_id=original.formula_id,
        shots=bad_shots,
        opening_hook=original.opening_hook,
        cta_text=original.cta_text,
        brand_mention_count=original.brand_mention_count,
    )
    canned = bad.model_dump_json()
    agent = ArchetypeVoiceRewriterAgent(_MockChatModel(response_text=canned))

    vars_ = _make_vars(original_script=original)
    with pytest.raises(ValueError, match="shot count changed"):
        asyncio.run(agent.a_rewrite_voice(vars=vars_))


def test_a_rewrite_voice_invokes_words_to_avoid_validator() -> None:
    """LLM 返回的脚本若含有禁词，``a_rewrite_voice`` 应抛 words_to_avoid 异常。"""
    original = _make_script()
    rewritten = _rewritten_clone(
        original,
        new_dialog="这是最强的产品",
        new_opening_hook="智者改写后的钩子",
    )
    canned = rewritten.model_dump_json()
    agent = ArchetypeVoiceRewriterAgent(_MockChatModel(response_text=canned))

    vars_ = _make_vars(original_script=original, words_to_avoid=["最强"])
    with pytest.raises(ValueError, match="words_to_avoid violated"):
        asyncio.run(agent.a_rewrite_voice(vars=vars_))


# ---------------------------------------------------------------------------
# 11. format_output salvage path
# ---------------------------------------------------------------------------


def test_format_output_handles_malformed_via_json_repair() -> None:
    """末尾缺右括号的截断 JSON 应被 json-repair 自动闭合后再校验。"""
    canned = _make_script().model_dump_json()
    raw = canned[:-1]  # 去掉末尾 } 模拟 LLM 截断
    agent = ArchetypeVoiceRewriterAgent(_MockChatModel(response_text=raw))

    result = agent.format_output(raw)

    assert isinstance(result, StoryScript)
    assert len(result.shots) == 4


def test_format_output_strict_path_works_for_clean_json() -> None:
    """干净 JSON 直接走 ``model_validate_json``，无需 ``json-repair``。"""
    canned = _make_script().model_dump_json()
    agent = ArchetypeVoiceRewriterAgent(_MockChatModel(response_text=canned))

    result = agent.format_output(canned)

    assert isinstance(result, StoryScript)
    assert result.formula_id == "dramatic_reversal"


# ---------------------------------------------------------------------------
# 12-14. Agent wiring
# ---------------------------------------------------------------------------


def test_agent_uses_json_schema_method() -> None:
    """构造函数应将 structured output method 固定为 ``json_schema``（D5）。"""
    agent = ArchetypeVoiceRewriterAgent(_MockChatModel(response_text="{}"))

    # AgentBase 把方法存到 _structured_output_method；属性名是稳定 API。
    assert agent._structured_output_method == "json_schema"  # noqa: SLF001


def test_agent_inherits_correct_output_model() -> None:
    """``output_model`` 必须是 ``StoryScript``，``prompt_template`` 必须是
    模板单例 ``ARCHETYPE_REWRITE_PROMPT``。"""
    agent = ArchetypeVoiceRewriterAgent(_MockChatModel(response_text="{}"))

    assert agent.output_model is StoryScript
    assert agent.prompt_template is ARCHETYPE_REWRITE_PROMPT
    # system_prompt 不为空，并明确包含"保留"关键字（结构保留是核心铁律）。
    assert agent.system_prompt
    assert "保留" in agent.system_prompt


def test_archetype_string_passed_to_prompt() -> None:
    """渲染后的提示词应包含 archetype 字符串与原始脚本片段。"""
    agent = ArchetypeVoiceRewriterAgent(_MockChatModel(response_text="{}"))
    vars_ = _make_vars(archetype="hero")

    rendered = agent.render_prompt(**vars_.model_dump())

    assert "hero" in rendered
    # 原始脚本以 dict/JSON 形式被注入，应能在渲染串中找到首镜 id。
    assert "shot_001" in rendered


def test_prompt_template_declares_template_referenced_input_variables() -> None:
    """``ARCHETYPE_REWRITE_PROMPT`` 实际暴露的输入变量应等于模板引用集合。

    背景：``PromptTemplate`` 构造时会以模板实际引用为准裁剪 ``input_variables``。
    虽然 Agent 在声明时显式列出了 6 个变量（含 ``archetype_description``，
    为后续模板演进保留接入点），但模板当前只渲染 5 个，故 ``input_variables``
    被裁剪为 5 项。本测试锁定这一不变量，避免模板演进时悄悄破坏对齐。
    """
    assert set(ARCHETYPE_REWRITE_PROMPT.input_variables) == {
        "original_script",
        "archetype",
        "tone_grid",
        "words_to_avoid",
        "preferred_vocab",
    }


def test_render_prompt_accepts_archetype_description_without_error() -> None:
    """渲染时多传 ``archetype_description`` 不应报错（jinja2 静默忽略未引用变量）。

    这保证了 ``a_rewrite_voice`` 把 ``ArchetypeRewriteVars.model_dump()``
    全量喂给提示词时不会出现 KeyError，未来若模板新增引用该字段也无需改 Agent。
    """
    agent = ArchetypeVoiceRewriterAgent(_MockChatModel(response_text="{}"))
    vars_ = _make_vars(archetype_description="智者：理性 / 克制 / 信息密度高")

    rendered = agent.render_prompt(**vars_.model_dump())

    assert isinstance(rendered, str)
    assert rendered  # 非空
