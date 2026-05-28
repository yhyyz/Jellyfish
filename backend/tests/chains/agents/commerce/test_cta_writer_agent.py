"""CTAWriterAgent 单元测试（W12 P2 TDD backfill）。

覆盖：

1. happy path：mock LLM 返回合法 JSON → 输出 :class:`CTAText`；
2. prompt 渲染：渲染后含 ``hardness`` / ``urgency_type`` / ``pattern_id``；
3. JSON drift 兜底：``json-repair`` 修复 unquoted key / trailing comma；
4. Pydantic 严格校验：缺字段或越界长度 → 抛 ``ValidationError``；
5. ``hardness`` 三档区分：soft / medium / hard 都能驱动到 LLM；
6. ``cta_text`` 时长约束：``max_length=120`` 命中边界。
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

from app.chains.agents.commerce.cta_writer_agent import (
    CTA_WRITER_PROMPT,
    CTAWriterAgent,
    _format_product_block,
)
from app.core.contracts.story import CTAText, CTAWriteVars


class _MockChatModel(BaseChatModel):
    """LangChain ``BaseChatModel`` mock：恒定返回单一字符串，避免触网。"""

    response: str = ""

    def __init__(self, response: str = "") -> None:
        super().__init__()
        object.__setattr__(self, "response", response)

    @property
    def _llm_type(self) -> str:  # pragma: no cover - LangChain 协议
        return "mock-cta-writer-chat-model"

    def _generate(  # type: ignore[override]
        self,
        messages: Any,  # pylint: disable=unused-argument
        stop: Any = None,  # pylint: disable=unused-argument
        run_manager: Any = None,  # pylint: disable=unused-argument
        **_kwargs: Any,
    ) -> ChatResult:
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=self.response))]
        )


def _valid_cta_json(
    *,
    cta_text: str = "今天下单立省 50 元，限量 100 份！",
    pattern_id: str = "p_scarcity_001",
    hardness: str = "medium",
    urgency_type: str = "scarcity",
    rationale: str | None = "稀缺感驱动",
) -> str:
    return json.dumps(
        {
            "cta_text": cta_text,
            "pattern_id": pattern_id,
            "hardness": hardness,
            "urgency_type": urgency_type,
            "rationale": rationale,
        },
        ensure_ascii=False,
    )


def _cta_vars(
    *,
    pattern_id: str = "p_scarcity_001",
    hardness: str = "medium",
    urgency_type: str = "scarcity",
    product_name: str = "代餐奶昔",
) -> CTAWriteVars:
    return CTAWriteVars(
        pattern_id=pattern_id,
        hardness=hardness,
        urgency_type=urgency_type,
        product_name=product_name,
        product_url="https://example.com/p/123",
        discount_text="立减 50 元",
        target_action="加购",
    )


# ---------------------------------------------------------------------------
# 1. happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_write_cta_returns_ctatext_on_valid_llm_output() -> None:
    """合法 LLM JSON → ``a_write_cta`` 输出 :class:`CTAText`。"""

    agent = CTAWriterAgent(_MockChatModel(_valid_cta_json()))

    result = await agent.a_write_cta(vars=_cta_vars())

    assert isinstance(result, CTAText)
    assert result.pattern_id == "p_scarcity_001"
    assert result.hardness == "medium"
    assert result.urgency_type == "scarcity"
    assert "限量" in result.cta_text


# ---------------------------------------------------------------------------
# 2. prompt 渲染
# ---------------------------------------------------------------------------


def test_cta_writer_prompt_renders_hardness_and_urgency_and_product() -> None:
    """``CTA_WRITER_PROMPT.format(...)`` 渲染后含 hardness/urgency_type/pattern。"""

    product_block = _format_product_block(
        _cta_vars(
            pattern_id="p_urgency_004",
            hardness="hard",
            urgency_type="urgency",
            product_name="精华液",
        )
    )
    rendered = CTA_WRITER_PROMPT.format(
        hardness="hard",
        product=product_block,
        urgency_type="urgency",
    )

    assert "hard" in rendered
    assert "urgency" in rendered
    assert "p_urgency_004" in rendered
    assert "精华液" in rendered


# ---------------------------------------------------------------------------
# 3. JSON drift 兜底
# ---------------------------------------------------------------------------


def test_format_output_recovers_from_unquoted_keys_and_trailing_comma() -> None:
    """unquoted key + 尾逗号 + 单引号 → ``json-repair`` 修复后仍能解析。"""

    malformed = (
        "{cta_text: '限时 24h，立省 100 元！',"
        " pattern_id: 'p_urgency_001',"
        " hardness: 'hard',"
        " urgency_type: 'urgency',"
        " rationale: '紧迫感',}"
    )
    agent = CTAWriterAgent(_MockChatModel(""))

    result = agent.format_output(malformed)

    assert isinstance(result, CTAText)
    assert result.cta_text == "限时 24h，立省 100 元！"
    assert result.hardness == "hard"
    assert result.urgency_type == "urgency"


# ---------------------------------------------------------------------------
# 4. Pydantic 严格校验
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_write_cta_raises_when_required_field_missing() -> None:
    """LLM 返回缺 ``urgency_type`` → 抛 :class:`ValidationError`。"""

    bad_json = json.dumps(
        {
            "cta_text": "立即加购",
            "pattern_id": "p_x",
            "hardness": "soft",
            # urgency_type 缺失
        },
        ensure_ascii=False,
    )
    agent = CTAWriterAgent(_MockChatModel(bad_json))

    with pytest.raises(ValidationError):
        await agent.a_write_cta(vars=_cta_vars())


# ---------------------------------------------------------------------------
# 5. hardness 三档区分（soft / medium / hard）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hardness",
    ["soft", "medium", "hard"],
)
async def test_a_write_cta_supports_three_hardness_levels(hardness: str) -> None:
    """soft / medium / hard 三档都能驱动 LLM 并回填同名字段。"""

    agent = CTAWriterAgent(
        _MockChatModel(_valid_cta_json(hardness=hardness))
    )

    result = await agent.a_write_cta(vars=_cta_vars(hardness=hardness))

    assert result.hardness == hardness


# ---------------------------------------------------------------------------
# 6. cta_text 时长约束 (max_length=120)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_write_cta_text_exceeding_max_length_fails() -> None:
    """``cta_text`` 超过 120 字符 → 抛 :class:`ValidationError`，
    保证下游"≤ 5 秒可读"约束在 schema 层早暴露。"""

    too_long = "购" * 121
    agent = CTAWriterAgent(_MockChatModel(_valid_cta_json(cta_text=too_long)))

    with pytest.raises(ValidationError):
        await agent.a_write_cta(vars=_cta_vars())


# ---------------------------------------------------------------------------
# 7. 配置常量 — D5 决策对齐
# ---------------------------------------------------------------------------


def test_agent_uses_json_schema_structured_output_method() -> None:
    """W4-T3 决策 D5：commerce agent 统一 ``json_schema`` 结构化输出。"""

    agent = CTAWriterAgent(_MockChatModel(""))

    assert agent._structured_output_method == "json_schema"
    assert set(CTA_WRITER_PROMPT.input_variables) == {
        "hardness",
        "product",
        "urgency_type",
    }
