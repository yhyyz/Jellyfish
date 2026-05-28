"""ArchetypeVoiceRewriterAgent 单元测试（W12 P2 TDD backfill）。

覆盖：

1. happy path：mock LLM 返回结构保留的 :class:`StoryScript` JSON → 通过；
2. prompt 渲染：渲染后含 ``archetype`` / ``tone_grid`` / ``words_to_avoid``；
3. JSON drift 兜底：``json-repair`` 修复 unquoted key / trailing comma；
4. Pydantic 严格校验：缺字段 → 抛 :class:`ValidationError`；
5. ``shots_id_invariant`` 校验：LLM 第一次丢失 / 改动 shot.id → ``ValueError``；
   重新拿到结构一致的 LLM 输出后流程恢复成功；
6. ``words_to_avoid`` 校验：禁词命中 → ``ValueError``；
7. 12 archetype × 10 tone：结构保留前提下任意人格 + tone_grid 都能成功。
"""

# pylint: disable=protected-access,too-few-public-methods

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ValidationError

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
    """LangChain ``BaseChatModel`` mock：可在多次调用之间切换返回值。

    ``responses`` 为顺序队列：每次 ``_generate`` 弹一个；耗尽后回退到
    ``default`` 字段。便于在测试中模拟 LLM 第一次输出脏数据、第二次
    才输出合法结构的"重试"流程。
    """

    responses: list[str] = []
    default: str = ""

    def __init__(self, responses: list[str] | None = None, default: str = "") -> None:
        super().__init__()
        object.__setattr__(self, "responses", list(responses or []))
        object.__setattr__(self, "default", default)

    @property
    def _llm_type(self) -> str:  # pragma: no cover - LangChain 协议
        return "mock-archetype-rewriter-chat-model"

    def _generate(  # type: ignore[override]
        self,
        messages: Any,  # pylint: disable=unused-argument
        stop: Any = None,  # pylint: disable=unused-argument
        run_manager: Any = None,  # pylint: disable=unused-argument
        **_kwargs: Any,
    ) -> ChatResult:
        if self.responses:
            content = self.responses.pop(0)
        else:
            content = self.default
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=content))]
        )


def _make_shot(
    *,
    shot_id: str,
    duration_sec: float = 5.0,
    dialog: str = "原始对白",
    is_brand_mention: bool = False,
) -> Shot:
    return Shot(
        id=shot_id,
        duration_sec=duration_sec,
        function="setup",
        shot_type="medium",
        camera_angle="eye_level",
        camera_movement="static",
        dialog=dialog,
        narration=None,
        product_focus_level="subtle",
        is_punchline=False,
        is_brand_mention=is_brand_mention,
        notes=None,
    )


def _base_script(*, opening_hook: str = "原始钩子", cta_text: str = "原始 CTA") -> StoryScript:
    """4 镜原始脚本，shot id = s1/s2/s3/s4，s2 含品牌口播。

    使用 4 镜（而不是 3 镜）是因为 :class:`StoryScript.shots` 的
    ``min_length=3`` 约束：当我们故意丢掉 1 个 shot 来测试镜数校验时，
    必须先在 Pydantic 层让脚本仍 ≥ 3 镜（即 4 → 3），才能让
    ``validate_structure_preserved`` 拿到机会比对 ``len`` 差异。
    """

    return StoryScript(
        total_duration_sec=20.0,
        total_shots=4,
        formula_id="formula-1",
        shots=[
            _make_shot(shot_id="s1", dialog="镜 1 原始对白"),
            _make_shot(shot_id="s2", dialog="镜 2 原始对白", is_brand_mention=True),
            _make_shot(shot_id="s3", dialog="镜 3 原始对白"),
            _make_shot(shot_id="s4", dialog="镜 4 原始对白"),
        ],
        opening_hook=opening_hook,
        cta_text=cta_text,
        brand_mention_count=1,
    )


def _rewritten_json(
    base: StoryScript,
    *,
    rewrite_dialog: str = "改写后的对白",
    keep_shot_ids: bool = True,
    drop_first_shot: bool = False,
) -> str:
    """构造与 ``base`` 结构一致 / 不一致的 LLM 输出 JSON。

    keep_shot_ids=False 时把第 1 个 shot 的 id 改写，触发结构校验失败；
    drop_first_shot=True 时丢掉首个 shot，触发 shot count 校验失败。
    """

    payload = base.model_dump()
    shots: list[dict[str, Any]] = list(payload["shots"])
    if drop_first_shot:
        shots = shots[1:]
    elif not keep_shot_ids:
        shots[0] = {**shots[0], "id": "s1_renamed"}
    for shot in shots:
        shot["dialog"] = rewrite_dialog
    payload["shots"] = shots
    payload["opening_hook"] = "改写后的钩子"
    payload["cta_text"] = "改写后的 CTA"
    return json.dumps(payload, ensure_ascii=False)


def _vars_from_script(
    script: StoryScript,
    *,
    archetype: str = "hero",
    tone_grid: dict[str, int] | None = None,
    words_to_avoid: list[str] | None = None,
) -> ArchetypeRewriteVars:
    return ArchetypeRewriteVars(
        original_script=script.model_dump(),
        archetype=archetype,
        archetype_description=f"{archetype} 人格的自然语言描述",
        tone_grid=tone_grid or {"formality": 5, "energy": 7},
        words_to_avoid=words_to_avoid or [],
        preferred_vocab=["真实", "可信"],
    )


# ---------------------------------------------------------------------------
# 1. happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_rewrite_voice_returns_structurally_preserved_script() -> None:
    """LLM 返回结构保留的 ``StoryScript`` → 校验通过并返回新脚本。"""

    base = _base_script()
    agent = ArchetypeVoiceRewriterAgent(
        _MockChatModel(default=_rewritten_json(base))
    )

    result = await agent.a_rewrite_voice(vars=_vars_from_script(base))

    assert isinstance(result, StoryScript)
    assert [s.id for s in result.shots] == ["s1", "s2", "s3", "s4"]
    assert all(s.dialog == "改写后的对白" for s in result.shots)
    assert result.opening_hook == "改写后的钩子"
    assert result.cta_text == "改写后的 CTA"


# ---------------------------------------------------------------------------
# 2. prompt 渲染
# ---------------------------------------------------------------------------


def test_archetype_prompt_renders_archetype_tone_grid_and_words() -> None:
    """``ARCHETYPE_REWRITE_PROMPT.format(...)`` 渲染含 archetype / tone_grid /
    words_to_avoid / preferred_vocab。"""

    rendered = ARCHETYPE_REWRITE_PROMPT.format(
        archetype="hero",
        archetype_description="hero 人格自然语言描述",
        tone_grid={"formality": 6, "energy": 8},
        original_script={"total_shots": 3},
        words_to_avoid=["最", "第一"],
        preferred_vocab=["真诚", "可靠"],
    )

    assert "hero" in rendered
    assert "formality" in rendered
    assert "最" in rendered
    assert "真诚" in rendered or "可靠" in rendered


# ---------------------------------------------------------------------------
# 3. JSON drift 兜底
# ---------------------------------------------------------------------------


def test_format_output_recovers_from_trailing_comma_via_json_repair() -> None:
    """``StoryScript`` JSON 带尾逗号 → ``json-repair`` 修复后仍可解析。"""

    base = _base_script()
    valid = _rewritten_json(base)
    # 在最外层对象 } 前插入一个尾逗号，破坏严格 JSON 但 json_repair 可修。
    malformed = valid[:-1] + ",}"
    agent = ArchetypeVoiceRewriterAgent(_MockChatModel(default=""))

    result = agent.format_output(malformed)

    assert isinstance(result, StoryScript)
    assert len(result.shots) == 4


# ---------------------------------------------------------------------------
# 4. Pydantic 严格校验
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_rewrite_voice_raises_validation_error_on_missing_field() -> None:
    """LLM 返回缺顶层 ``opening_hook`` → 抛 :class:`ValidationError`。"""

    base = _base_script()
    payload = base.model_dump()
    payload.pop("opening_hook")
    bad_json = json.dumps(payload, ensure_ascii=False)
    agent = ArchetypeVoiceRewriterAgent(_MockChatModel(default=bad_json))

    with pytest.raises(ValidationError):
        await agent.a_rewrite_voice(vars=_vars_from_script(base))


# ---------------------------------------------------------------------------
# 5. shots_id_invariant 校验：丢 shot id → ValueError；
#    重新调用拿到合规输出后流程恢复成功（"retry"语义）。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_rewrite_voice_raises_when_shot_id_changed_then_recovers() -> None:
    """模拟 ModelRetry 语义：

    - 第一次 LLM 返回把 ``shots[0].id`` 改名 → 触发 ``ValueError``；
    - 把 LLM 切回正确输出后再调一次，结构校验通过返回 :class:`StoryScript`。
    """

    base = _base_script()

    # 第一次：LLM 改写后第一个 shot 的 id 被换名 → 应抛错。
    bad_llm = _MockChatModel(default=_rewritten_json(base, keep_shot_ids=False))
    agent_bad = ArchetypeVoiceRewriterAgent(bad_llm)
    with pytest.raises(ValueError) as excinfo:
        await agent_bad.a_rewrite_voice(vars=_vars_from_script(base))
    assert "id" in str(excinfo.value)

    # 第二次：拿到合规 LLM 输出 → 流程恢复，返回 StoryScript。
    good_llm = _MockChatModel(default=_rewritten_json(base, keep_shot_ids=True))
    agent_good = ArchetypeVoiceRewriterAgent(good_llm)

    result = await agent_good.a_rewrite_voice(vars=_vars_from_script(base))
    assert isinstance(result, StoryScript)
    assert [s.id for s in result.shots] == ["s1", "s2", "s3", "s4"]


@pytest.mark.asyncio
async def test_a_rewrite_voice_raises_when_shot_count_changed() -> None:
    """LLM 删掉首个 shot → 镜数变化 → ``ValueError`` 且消息含 "shot count"。"""

    base = _base_script()
    agent = ArchetypeVoiceRewriterAgent(
        _MockChatModel(default=_rewritten_json(base, drop_first_shot=True))
    )

    with pytest.raises(ValueError, match="shot count"):
        await agent.a_rewrite_voice(vars=_vars_from_script(base))


# ---------------------------------------------------------------------------
# 6. words_to_avoid 校验
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_rewrite_voice_raises_when_words_to_avoid_violated() -> None:
    """改写结果含禁词 → 抛 :class:`ValueError` 列出命中词。"""

    base = _base_script()
    agent = ArchetypeVoiceRewriterAgent(
        _MockChatModel(default=_rewritten_json(base, rewrite_dialog="这是最最最棒的产品"))
    )

    with pytest.raises(ValueError, match="words_to_avoid"):
        await agent.a_rewrite_voice(
            vars=_vars_from_script(base, words_to_avoid=["最"])
        )


# ---------------------------------------------------------------------------
# 7. 12 archetype × 10 tone 矩阵：结构保留前提下都能通过
# ---------------------------------------------------------------------------


_TWELVE_ARCHETYPES: tuple[str, ...] = (
    "innocent",
    "everyman",
    "hero",
    "outlaw",
    "explorer",
    "creator",
    "ruler",
    "magician",
    "lover",
    "caregiver",
    "jester",
    "sage",
)
_TEN_TONE_LEVELS: tuple[int, ...] = tuple(range(1, 11))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "archetype,tone_level",
    [(_TWELVE_ARCHETYPES[i % 12], _TEN_TONE_LEVELS[i % 10]) for i in range(12)],
)
async def test_a_rewrite_voice_supports_multiple_archetype_tone_combos(
    archetype: str,
    tone_level: int,
) -> None:
    """12 archetype × 10 tone 中代表性组合：只要结构保留就能通过。"""

    base = _base_script()
    agent = ArchetypeVoiceRewriterAgent(
        _MockChatModel(default=_rewritten_json(base))
    )

    result = await agent.a_rewrite_voice(
        vars=_vars_from_script(
            base,
            archetype=archetype,
            tone_grid={
                "formality": tone_level,
                "energy": (tone_level + 3) % 11,
                "warmth": (tone_level + 5) % 11,
            },
        )
    )

    assert isinstance(result, StoryScript)
    assert len(result.shots) == 4


# ---------------------------------------------------------------------------
# 8. 配置常量 — D5 决策对齐
# ---------------------------------------------------------------------------


def test_agent_uses_json_schema_structured_output_method() -> None:
    """W4-T3 决策 D5：commerce agent 统一 ``json_schema`` 结构化输出。"""

    agent = ArchetypeVoiceRewriterAgent(_MockChatModel(default=""))

    assert agent._structured_output_method == "json_schema"
    assert "archetype" in ARCHETYPE_REWRITE_PROMPT.input_variables
    assert "tone_grid" in ARCHETYPE_REWRITE_PROMPT.input_variables
    assert "words_to_avoid" in ARCHETYPE_REWRITE_PROMPT.input_variables
