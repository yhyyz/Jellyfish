"""``DurationRewriterAgent`` 单元测试（P3 W17 T17-7 子组件）。

为何存在
--------

``ChapterAvPlanner`` 在 ``llm_rewrite`` 分支调用此 Agent，请求把
``original_text`` 改写为 ``≤ target_chars`` 字符的等价文本。Agent 必须：

1. 通过结构化输出（json_schema）拿到 ``{rewritten_text, char_count}``；
2. 在 LLM 偶发跑偏（带 markdown 包裹 / 多余字段 / 字数超限）时容忍并归一化；
3. 暴露异步入口 ``a_rewrite_to_target(vars=...)``，与
   ``ArchetypeVoiceRewriterAgent`` 风格对齐；
4. 可被 ``BaseChatModel`` 桩模型驱动，无需真实网络调用。

本文件用 ``_MockChatModel`` 把 LLM 输出钉死在固定 JSON 上，
专注断言 Agent 的 IO 形态与字数硬约束。
"""

# pylint: disable=protected-access,too-few-public-methods,redefined-outer-name

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.chains.agents.commerce.duration_rewriter_agent import (
    DurationRewriteResult,
    DurationRewriteVars,
    DurationRewriterAgent,
)
from app.models.types import DialogueLineMode


class _MockChatModel(BaseChatModel):
    """LangChain ``BaseChatModel`` 桩：恒定返回构造时给出的字符串。"""

    response: str = ""

    def __init__(self, response: str = "", **_kwargs: Any) -> None:
        super().__init__()
        object.__setattr__(self, "response", response)

    @property
    def _llm_type(self) -> str:  # pragma: no cover - LangChain 协议要求
        return "mock-duration-rewriter-chat-model"

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


# ---------------------------------------------------------------------------
# 1. 正常路径：LLM 返回合法 JSON
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_rewrites_text_when_llm_returns_valid_json() -> None:
    """LLM 返回 ``{rewritten_text, char_count}`` JSON：Agent 解出强类型对象。"""

    payload = {"rewritten_text": "短一点的台词", "char_count": 6}
    llm = _MockChatModel(json.dumps(payload, ensure_ascii=False))
    agent = DurationRewriterAgent(llm)

    result = await agent.a_rewrite_to_target(
        vars=DurationRewriteVars(
            original_text="原本这段台词非常长长到无法在镜头里念完",
            target_chars=8,
            line_mode=DialogueLineMode.dialogue,
        )
    )

    assert isinstance(result, DurationRewriteResult)
    assert result.rewritten_text == "短一点的台词"
    assert result.char_count == 6


# ---------------------------------------------------------------------------
# 2. format_output 兜底：带 markdown 围栏的 JSON
# ---------------------------------------------------------------------------


def test_format_output_strips_markdown_fences() -> None:
    """LLM 偶尔会用 ```json``` 包裹输出：``format_output`` 应能兜底解出。"""

    raw = "```json\n{\"rewritten_text\": \"hi\", \"char_count\": 2}\n```"
    llm = _MockChatModel("")
    agent = DurationRewriterAgent(llm)
    parsed = agent.format_output(raw)
    assert parsed.rewritten_text == "hi"
    assert parsed.char_count == 2


# ---------------------------------------------------------------------------
# 3. 字数硬约束：输出过长时 Agent 会主动截断
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_caps_output_when_exceeds_target_chars() -> None:
    """LLM 没遵守 ``≤ target_chars`` 时，Agent 必须截断，避免下游再次超时。"""

    payload = {"rewritten_text": "这段改写后的文本依然超过了限制", "char_count": 99}
    llm = _MockChatModel(json.dumps(payload, ensure_ascii=False))
    agent = DurationRewriterAgent(llm)

    result = await agent.a_rewrite_to_target(
        vars=DurationRewriteVars(
            original_text="原始非常长的台词",
            target_chars=5,
            line_mode=DialogueLineMode.voice_over,
        )
    )

    # Agent 兜底：要么自己截断到 ≤ 5，要么 raise；这里走截断分支。
    assert len(result.rewritten_text) <= 5
    # char_count 必须与 rewritten_text 一致，避免下游基于错误字数再决策。
    assert result.char_count == len(result.rewritten_text)


# ---------------------------------------------------------------------------
# 4. ``DurationRewriteVars`` 校验
# ---------------------------------------------------------------------------


def test_rewrite_vars_requires_target_chars_positive() -> None:
    """``target_chars`` 必须 ≥ 1：0 / 负值无业务意义。"""

    with pytest.raises(ValueError):
        DurationRewriteVars(
            original_text="abc",
            target_chars=0,
            line_mode=DialogueLineMode.dialogue,
        )
