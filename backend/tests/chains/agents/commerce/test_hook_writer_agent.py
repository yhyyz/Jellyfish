"""HookWriterAgent 单元测试（W12 P2 TDD backfill）。

覆盖：

1. happy path：mock LLM 返回合法 JSON → 输出 :class:`ShotHook`；
2. prompt 渲染：渲染后包含 ``pattern_id`` 与商品/受众片段；
3. JSON drift 兜底：``json-repair`` 修复未引号 key / 尾逗号 / 单引号；
4. Pydantic 严格校验：缺字段或越界长度 → 抛 ``ValidationError``；
5. 长 script 边界：``hook_text`` 命中 ``max_length=80`` 上限；
6. 配置常量：``structured_output_method='json_schema'`` 与模板 ID 一致。
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

from app.chains.agents.commerce.hook_writer_agent import (
    HOOK_WRITER_PROMPT,
    HookWriterAgent,
)
from app.core.contracts.story import HookWriteVars, ShotHook


class _MockChatModel(BaseChatModel):
    """复用 W4-T3 风格的 LangChain ``BaseChatModel`` mock：恒定返回单字符串。

    用于驱动 ``aextract`` 走 ``arun + format_output`` 路径，避免触网。
    """

    response: str = ""

    def __init__(self, response: str = "") -> None:
        super().__init__()
        object.__setattr__(self, "response", response)

    @property
    def _llm_type(self) -> str:  # pragma: no cover - LangChain 协议
        return "mock-hook-writer-chat-model"

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


def _valid_hook_json(
    *,
    hook_text: str = "你以为减脂只能挨饿？",
    pattern_id: str = "p_question_001",
    pattern_type: str = "question",
    rationale: str | None = "提问句直击痛点",
) -> str:
    return json.dumps(
        {
            "hook_text": hook_text,
            "pattern_id": pattern_id,
            "pattern_type": pattern_type,
            "rationale": rationale,
        },
        ensure_ascii=False,
    )


def _hook_vars(
    *,
    pattern_id: str = "p_question_001",
    pattern_type: str = "question",
    product_name: str = "代餐奶昔",
) -> HookWriteVars:
    return HookWriteVars(
        pattern_id=pattern_id,
        pattern_type=pattern_type,
        product_name=product_name,
        product_description="低卡饱腹",
        audience_pain_points=["减肥屡屡失败"],
        audience_demographics={"age": "25-35", "gender": "female"},
    )


# ---------------------------------------------------------------------------
# 1. happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_write_hook_returns_shothook_on_valid_llm_output() -> None:
    """LLM 返回合法 JSON → ``a_write_hook`` 输出 :class:`ShotHook`。"""

    agent = HookWriterAgent(_MockChatModel(_valid_hook_json()))

    result = await agent.a_write_hook(vars=_hook_vars())

    assert isinstance(result, ShotHook)
    assert result.hook_text == "你以为减脂只能挨饿？"
    assert result.pattern_id == "p_question_001"
    assert result.pattern_type == "question"
    assert result.rationale == "提问句直击痛点"


# ---------------------------------------------------------------------------
# 2. 提示词模板渲染
# ---------------------------------------------------------------------------


def test_hook_writer_prompt_renders_pattern_id_and_context() -> None:
    """``HOOK_WRITER_PROMPT.format(...)`` 渲染后含 ``pattern_id`` + 商品/受众片段。"""

    rendered = HOOK_WRITER_PROMPT.format(
        pattern_id="p_question_007",
        product={"name": "代餐", "description": "低卡饱腹"},
        audience={
            "pain_points": ["减脂屡败"],
            "demographics": {"age": "25-35"},
        },
    )

    assert "p_question_007" in rendered
    assert "代餐" in rendered
    assert "减脂" in rendered


# ---------------------------------------------------------------------------
# 3. JSON drift 兜底（json-repair fallback）
# ---------------------------------------------------------------------------


def test_format_output_recovers_from_unquoted_keys_and_trailing_comma() -> None:
    """带未引号 key + 尾逗号 + 单引号 → json-repair 修复后仍能解析。"""

    malformed = (
        "{hook_text: '只要 30 秒，让你瘦 5 斤！',"
        " pattern_id: 'p_numerical_001',"
        " pattern_type: 'numerical',"
        " rationale: 'numerical-driven',}"
    )
    agent = HookWriterAgent(_MockChatModel(""))

    result = agent.format_output(malformed)

    assert isinstance(result, ShotHook)
    assert result.hook_text == "只要 30 秒，让你瘦 5 斤！"
    assert result.pattern_id == "p_numerical_001"
    assert result.pattern_type == "numerical"


# ---------------------------------------------------------------------------
# 4. Pydantic 严格校验
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_write_hook_raises_when_required_field_missing() -> None:
    """LLM 返回缺 ``pattern_id`` → 抛 :class:`ValidationError`。"""

    bad_json = json.dumps(
        {
            "hook_text": "好奇钩子",
            # pattern_id 缺失
            "pattern_type": "curiosity",
        },
        ensure_ascii=False,
    )
    agent = HookWriterAgent(_MockChatModel(bad_json))

    with pytest.raises(ValidationError):
        await agent.a_write_hook(vars=_hook_vars())


# ---------------------------------------------------------------------------
# 5. 长 script 边界 — hook_text 长度上限 (80 字)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_write_hook_long_text_within_max_length_passes() -> None:
    """``hook_text`` 在 80 字符上限内仍能成功解析（覆盖 long script 边界）。"""

    long_text = "钩" * 80
    agent = HookWriterAgent(_MockChatModel(_valid_hook_json(hook_text=long_text)))

    result = await agent.a_write_hook(vars=_hook_vars())

    assert isinstance(result, ShotHook)
    assert len(result.hook_text) == 80


@pytest.mark.asyncio
async def test_a_write_hook_text_exceeding_max_length_fails() -> None:
    """``hook_text`` 超过 80 字符 → 抛 :class:`ValidationError`。

    模拟长 script (target_duration_sec >= 120) 场景下 LLM 输出过长导致的
    drift：``ShotHook.hook_text`` 受 ``max_length=80`` 约束，确保边界下游
    生产仍然能尽早暴露契约违规。
    """

    too_long = "钩" * 81
    agent = HookWriterAgent(_MockChatModel(_valid_hook_json(hook_text=too_long)))

    with pytest.raises(ValidationError):
        await agent.a_write_hook(vars=_hook_vars())


# ---------------------------------------------------------------------------
# 6. 配置常量 — D5 决策对齐
# ---------------------------------------------------------------------------


def test_agent_uses_json_schema_structured_output_method() -> None:
    """W4-T3 决策 D5：commerce agent 统一使用 ``json_schema`` 结构化输出。"""

    agent = HookWriterAgent(_MockChatModel(""))

    assert agent._structured_output_method == "json_schema"
    assert set(HOOK_WRITER_PROMPT.input_variables) == {
        "pattern_id",
        "product",
        "audience",
    }
