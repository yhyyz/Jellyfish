"""CTAWriterAgent 解析与契约回归测试。

覆盖：
    - 完整 JSON 流程：``a_write_cta`` 返回 ``CTAText`` 实例；
    - prompt 渲染：``CTAWriteVars`` 关键字段正确注入到模板与系统提示词；
    - ``format_output`` 兼容 unquoted key / trailing comma 等 LLM 常见偏差；
    - Pydantic 约束：``cta_text`` 长度边界、``hardness`` / ``urgency_type`` 必填；
    - Agent 元数据：``structured_output_method == "json_schema"``。
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ValidationError

from app.chains.agents.commerce.cta_writer_agent import (
    CTA_WRITER_PROMPT,
    CTAWriterAgent,
)
from app.core.contracts.story import CTAText, CTAWriteVars


_VALID_CTA_JSON = """{
    "cta_text": "现货仅剩 30 件，立即下单锁定折扣！",
    "pattern_id": "scarcity_v1",
    "hardness": "hard",
    "urgency_type": "scarcity",
    "rationale": "强调库存有限并直接引导下单"
}"""


_DEFAULT_VARS = CTAWriteVars(
    pattern_id="scarcity_v1",
    hardness="hard",
    urgency_type="scarcity",
    product_name="iPhone 15 Pro",
    product_url="https://example.com/p/iphone-15-pro",
    discount_text="限时 9 折",
    target_action="下单",
)


class _MockChatModel(BaseChatModel):
    """伪 LLM：始终回放固定字符串，并记录每次调用的 messages。"""

    def __init__(self, response: str) -> None:
        super().__init__()
        # 用 object.__setattr__ 绕过 pydantic v2 的字段保护。
        object.__setattr__(self, "_response", response)
        object.__setattr__(self, "calls", [])

    @property
    def _llm_type(self) -> str:  # pragma: no cover - 仅 LangChain 内部识别用
        return "mock-chat-model"

    def _generate(  # type: ignore[override]
        self,
        messages: Any,
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.calls.append(messages)  # type: ignore[attr-defined]
        return ChatResult(
            generations=[
                ChatGeneration(message=AIMessage(content=self._response))  # type: ignore[attr-defined]
            ]
        )


def _rendered_prompt_text(mock: _MockChatModel) -> str:
    """从 mock 的最后一次调用提取渲染后 prompt 文本。"""
    assert mock.calls, "mock 未被调用"  # type: ignore[attr-defined]
    last_messages = mock.calls[-1]  # type: ignore[attr-defined]
    pieces: list[str] = []
    for msg in last_messages:
        content = getattr(msg, "content", None)
        pieces.append(content if isinstance(content, str) else str(msg))
    return "\n".join(pieces)


# ---------------------------------------------------------------------------
# 1. 完整 JSON 流程
# ---------------------------------------------------------------------------


async def test_a_write_cta_returns_valid_pydantic() -> None:
    """mock 返回合法 JSON 时，``a_write_cta`` 应返回 CTAText。"""
    agent = CTAWriterAgent(_MockChatModel(_VALID_CTA_JSON))

    result = await agent.a_write_cta(vars=_DEFAULT_VARS)

    assert isinstance(result, CTAText)
    assert result.cta_text == "现货仅剩 30 件，立即下单锁定折扣！"
    assert result.pattern_id == "scarcity_v1"
    assert result.hardness == "hard"
    assert result.urgency_type == "scarcity"
    assert result.rationale == "强调库存有限并直接引导下单"


# ---------------------------------------------------------------------------
# 2-4. format_output：清洁 / unquoted key / trailing comma
# ---------------------------------------------------------------------------


def test_format_output_handles_clean_json() -> None:
    """合法 JSON 直接由 ``model_validate_json`` 通过。"""
    agent = CTAWriterAgent(_MockChatModel(_VALID_CTA_JSON))

    result = agent.format_output(_VALID_CTA_JSON)

    assert isinstance(result, CTAText)
    assert result.pattern_id == "scarcity_v1"
    assert result.urgency_type == "scarcity"


def test_format_output_handles_unquoted_keys_via_json_repair() -> None:
    """未加引号的对象键名应被 json-repair 修复后再校验。"""
    raw = (
        "{cta_text:'限时折扣，立即下单！',"
        "pattern_id:'urgency_v1',"
        "hardness:'medium',"
        "urgency_type:'urgency',"
        "rationale:'倒计时驱动转化'}"
    )
    agent = CTAWriterAgent(_MockChatModel(raw))

    result = agent.format_output(raw)

    assert isinstance(result, CTAText)
    assert result.cta_text == "限时折扣，立即下单！"
    assert result.pattern_id == "urgency_v1"
    assert result.hardness == "medium"
    assert result.urgency_type == "urgency"


def test_format_output_handles_trailing_comma_via_json_repair() -> None:
    """对象的尾逗号应被 json-repair 容错。"""
    raw = """{
        "cta_text": "好评 10W+，加购即享福利！",
        "pattern_id": "social_proof_v1",
        "hardness": "soft",
        "urgency_type": "social_proof",
        "rationale": "用社交证据提升信任",
    }"""
    agent = CTAWriterAgent(_MockChatModel(raw))

    result = agent.format_output(raw)

    assert isinstance(result, CTAText)
    assert result.cta_text == "好评 10W+，加购即享福利！"
    assert result.urgency_type == "social_proof"


# ---------------------------------------------------------------------------
# 5-6. Pydantic 长度约束
# ---------------------------------------------------------------------------


def test_cta_text_under_min_length_rejected() -> None:
    """``cta_text`` 长度小于 4 时 Pydantic 应拒绝。"""
    raw = """{
        "cta_text": "买",
        "pattern_id": "benefit_v1",
        "hardness": "hard",
        "urgency_type": "benefit",
        "rationale": null
    }"""
    agent = CTAWriterAgent(_MockChatModel(raw))

    with pytest.raises(ValidationError):
        agent.format_output(raw)


def test_cta_text_over_max_length_rejected() -> None:
    """``cta_text`` 长度超过 120 时 Pydantic 应拒绝。"""
    too_long_text = "立即下单 " * 30  # 远超 120 字
    raw = (
        '{"cta_text":"' + too_long_text + '",'
        '"pattern_id":"benefit_v1",'
        '"hardness":"hard",'
        '"urgency_type":"benefit",'
        '"rationale":null}'
    )
    agent = CTAWriterAgent(_MockChatModel(raw))

    with pytest.raises(ValidationError):
        agent.format_output(raw)


# ---------------------------------------------------------------------------
# 7-8. 必填字段
# ---------------------------------------------------------------------------


def test_hardness_required() -> None:
    """缺失 ``hardness`` 字段时 Pydantic 应拒绝。"""
    raw = """{
        "cta_text": "立即下单领取专属优惠！",
        "pattern_id": "benefit_v1",
        "urgency_type": "benefit",
        "rationale": null
    }"""
    agent = CTAWriterAgent(_MockChatModel(raw))

    with pytest.raises(ValidationError):
        agent.format_output(raw)


def test_urgency_type_required() -> None:
    """缺失 ``urgency_type`` 字段时 Pydantic 应拒绝。"""
    raw = """{
        "cta_text": "立即下单领取专属优惠！",
        "pattern_id": "benefit_v1",
        "hardness": "medium",
        "rationale": null
    }"""
    agent = CTAWriterAgent(_MockChatModel(raw))

    with pytest.raises(ValidationError):
        agent.format_output(raw)


# ---------------------------------------------------------------------------
# 9. Agent 元数据
# ---------------------------------------------------------------------------


def test_agent_uses_json_schema_method() -> None:
    """D5 决策：commerce 写作 agent 一律使用 json_schema strict。"""
    agent = CTAWriterAgent(_MockChatModel(""))

    # pylint: disable=protected-access
    assert agent._structured_output_method == "json_schema"
    assert agent.output_model is CTAText
    assert sorted(CTA_WRITER_PROMPT.input_variables) == [
        "hardness",
        "product",
        "urgency_type",
    ]


# ---------------------------------------------------------------------------
# 10. 输入变量注入
# ---------------------------------------------------------------------------


async def test_a_write_cta_passes_vars_correctly() -> None:
    """``CTAWriteVars`` 关键字段应正确出现在渲染后的提示词中。"""
    mock = _MockChatModel(_VALID_CTA_JSON)
    agent = CTAWriterAgent(mock)

    await agent.a_write_cta(vars=_DEFAULT_VARS)

    rendered = _rendered_prompt_text(mock)
    # hardness / urgency_type 直接进入 jinja 模板槽位
    assert "hard" in rendered
    assert "scarcity" in rendered
    # 商品/动作/pattern 信息打包进 product 段落
    assert "iPhone 15 Pro" in rendered
    assert "https://example.com/p/iphone-15-pro" in rendered
    assert "限时 9 折" in rendered
    assert "下单" in rendered
    assert "scarcity_v1" in rendered
