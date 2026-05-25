"""ProductExtractorAgent 解析与契约回归测试。

覆盖：
    - 完整 JSON 流程：``a_extract_product`` 返回 ``ProductExtractionResult`` 实例；
    - prompt 渲染：``target_fields`` 列表正确注入到模板；
    - ``format_output`` 兼容 unquoted key / trailing comma 等 LLM 常见偏差；
    - ``format_output`` 在完全无法解析时抛出 ``ValidationError``；
    - Pydantic 约束（如 ``selling_points`` ≤ 5）在抽取时仍生效；
    - Agent 元数据：``structured_output_method == "json_schema"``、``output_model``。
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ValidationError

from app.chains.agents.commerce import ProductExtractorAgent
from app.chains.agents.commerce.product_extractor_agent import (
    PRODUCT_EXTRACTION_PROMPT,
)
from app.core.contracts.story import ProductExtractionResult

# ---------------------------------------------------------------------------
# 公共 fixture
# ---------------------------------------------------------------------------

_VALID_PRODUCT_JSON = """{
    "name": "iPhone 15 Pro",
    "brand": "Apple",
    "category": "electronics",
    "description": "搭载 A17 Pro 芯片的旗舰手机，主打性能与影像能力。",
    "price_anchor": 7999.0,
    "sku": "IP15P-256-TI",
    "selling_points": ["A17 Pro 芯片", "钛金属机身", "5x 长焦"],
    "pain_points_solved": ["旗舰性能不足", "续航焦虑"],
    "target_audience": {
        "age_range": "25-45",
        "gender": "all",
        "motivation": "high-end-mobile"
    },
    "catchphrases": ["Pro 之巅"],
    "competitor_names": ["Galaxy S24 Ultra"],
    "health_disclaimer_required": false
}"""


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
        # 记录调用，便于断言渲染后的 prompt 内容。
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
# 解析与契约
# ---------------------------------------------------------------------------


def test_extract_product_returns_pydantic_model() -> None:
    """mock 返回合法 JSON 时，``extract`` 应返回 ProductExtractionResult。"""
    agent = ProductExtractorAgent(_MockChatModel(_VALID_PRODUCT_JSON))

    result = agent.extract(raw_text="iPhone 商品页粘贴文本", target_fields="全部字段")

    assert isinstance(result, ProductExtractionResult)
    assert result.name == "iPhone 15 Pro"
    assert result.brand == "Apple"
    assert result.category == "electronics"
    assert len(result.selling_points) == 3
    assert result.health_disclaimer_required is False


async def test_extract_product_with_target_fields() -> None:
    """``target_fields`` 列表应以逗号拼接形式出现在渲染后的 prompt 中。"""
    mock = _MockChatModel(_VALID_PRODUCT_JSON)
    agent = ProductExtractorAgent(mock)

    result = await agent.a_extract_product(
        raw_text="iPhone 详情页内容",
        target_fields=["name", "brand", "selling_points"],
    )

    assert isinstance(result, ProductExtractionResult)

    rendered = _rendered_prompt_text(mock)
    assert "name" in rendered
    assert "brand" in rendered
    assert "selling_points" in rendered
    # 逗号拼接后应能命中三字段同时出现的子串。
    assert "name, brand, selling_points" in rendered


async def test_extract_product_uses_full_fields_when_target_fields_none() -> None:
    """``target_fields=None`` 时应使用占位文案 ``"全部字段"`` 注入模板。"""
    mock = _MockChatModel(_VALID_PRODUCT_JSON)
    agent = ProductExtractorAgent(mock)

    await agent.a_extract_product(raw_text="商品物料", target_fields=None)

    rendered = _rendered_prompt_text(mock)
    assert "全部字段" in rendered


# ---------------------------------------------------------------------------
# format_output：json-repair 兜底
# ---------------------------------------------------------------------------


def test_format_output_handles_unquoted_keys_via_json_repair() -> None:
    """未加引号的对象键名应被 json-repair 修复后再校验。"""
    raw = (
        "{name:'iPhone 15',brand:'Apple',category:'electronics',"
        "description:'高端旗舰机',price_anchor:null,sku:null,"
        "selling_points:['A17 Pro','钛金属'],"
        "pain_points_solved:['旗舰性能不足'],"
        "target_audience:{age_range:'25-45'},"
        "catchphrases:['Pro 之巅'],competitor_names:['Galaxy'],"
        "health_disclaimer_required:false}"
    )
    agent = ProductExtractorAgent(_MockChatModel(raw))

    result = agent.format_output(raw)

    assert isinstance(result, ProductExtractionResult)
    assert result.name == "iPhone 15"
    assert result.brand == "Apple"
    assert result.competitor_names == ["Galaxy"]


def test_format_output_handles_trailing_comma_via_json_repair() -> None:
    """对象/数组的尾逗号应被 json-repair 容错。"""
    raw = """{
        "name": "iPhone 15",
        "brand": "Apple",
        "category": "electronics",
        "description": "高端旗舰机",
        "price_anchor": null,
        "sku": null,
        "selling_points": ["A17 Pro",],
        "pain_points_solved": ["旗舰性能不足",],
        "target_audience": {"age_range": "25-45",},
        "catchphrases": ["Pro 之巅",],
        "competitor_names": ["Galaxy",],
        "health_disclaimer_required": false,
    }"""
    agent = ProductExtractorAgent(_MockChatModel(raw))

    result = agent.format_output(raw)

    assert isinstance(result, ProductExtractionResult)
    assert result.competitor_names == ["Galaxy"]
    assert result.selling_points == ["A17 Pro"]


def test_format_output_raises_on_completely_invalid() -> None:
    """完全无法解析的输入应抛出 ValidationError。"""
    agent = ProductExtractorAgent(_MockChatModel(""))

    with pytest.raises(ValidationError):
        agent.format_output("not json at all !!!")


# ---------------------------------------------------------------------------
# Pydantic 约束
# ---------------------------------------------------------------------------


def test_extract_product_rejects_too_many_selling_points() -> None:
    """``selling_points`` 超过 5 条时 Pydantic 应拒绝。"""
    too_many_payload = """{
        "name": "X",
        "brand": null,
        "category": "electronics",
        "description": "占位描述",
        "price_anchor": null,
        "sku": null,
        "selling_points": ["s1","s2","s3","s4","s5","s6"],
        "pain_points_solved": [],
        "target_audience": {},
        "catchphrases": [],
        "competitor_names": [],
        "health_disclaimer_required": false
    }"""
    agent = ProductExtractorAgent(_MockChatModel(too_many_payload))

    with pytest.raises(ValidationError):
        agent.extract(raw_text="任意输入")


# ---------------------------------------------------------------------------
# Agent 元数据
# ---------------------------------------------------------------------------


def test_agent_uses_json_schema_method() -> None:
    """D5 决策：商品/脚本/合规三个 commerce agent 一律使用 json_schema strict。"""
    agent = ProductExtractorAgent(_MockChatModel(""))

    # pylint: disable=protected-access
    assert agent._structured_output_method == "json_schema"


def test_agent_inherits_correct_output_model() -> None:
    """``output_model`` 必须为 ``ProductExtractionResult``。"""
    agent = ProductExtractorAgent(_MockChatModel(""))

    assert agent.output_model is ProductExtractionResult


def test_prompt_template_input_variables() -> None:
    """模板的输入变量必须是 ``raw_text`` 与 ``target_fields``。"""
    assert sorted(PRODUCT_EXTRACTION_PROMPT.input_variables) == [
        "raw_text",
        "target_fields",
    ]
