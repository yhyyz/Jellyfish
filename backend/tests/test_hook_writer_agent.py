"""HookWriterAgent 解析与契约回归测试。

覆盖：
    - 完整 JSON 流程：``a_write_hook`` 返回 ``ShotHook`` 实例并正确传参；
    - ``format_output`` 兼容 unquoted key / trailing comma 等 LLM 常见偏差；
    - ``ShotHook`` Pydantic 边界校验（``hook_text`` min/max length 与必填字段）；
    - Agent 元数据：``structured_output_method == "json_schema"``、``output_model``。
"""

from __future__ import annotations

import asyncio
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


# ---------------------------------------------------------------------------
# 公共 fixture
# ---------------------------------------------------------------------------


_VALID_HOOK_JSON = json.dumps(
    {
        "hook_text": "你以为夜里失眠是缺觉？其实是它没到位",
        "pattern_id": "conflict_001",
        "pattern_type": "conflict",
        "rationale": "用反差制造认知冲突，引发观众继续观看",
    },
    ensure_ascii=False,
)


class _MockChatModel(BaseChatModel):
    """伪 LLM：始终回放固定字符串，并记录每次调用的 messages。

    存在原因：
        HookWriterAgent 通过 AgentBase 的 ``aextract`` 调用模型，本类提供
        不依赖外部 LLM 的最小可用实现；``with_structured_output`` 会触发
        ``NotImplementedError``，由 AgentBase 捕获后回退到原始字符串解析路径。
    """

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


def _make_vars() -> HookWriteVars:
    """构造测试用 ``HookWriteVars``，覆盖所有字段非空场景。"""
    return HookWriteVars(
        pattern_id="conflict_001",
        pattern_type="conflict",
        product_name="深睡褪黑素软糖",
        product_description="低糖配方，10 分钟入睡",
        audience_pain_points=["夜里失眠", "白天精神差"],
        audience_demographics={"age_range": "25-40", "gender": "female"},
    )


# ---------------------------------------------------------------------------
# 1. 端到端：a_write_hook 返回有效 Pydantic
# ---------------------------------------------------------------------------


def test_a_write_hook_returns_valid_pydantic() -> None:
    """mock 返回合法 JSON 时，``a_write_hook`` 应返回 ``ShotHook`` 实例。"""
    agent = HookWriterAgent(_MockChatModel(_VALID_HOOK_JSON))

    result = asyncio.run(agent.a_write_hook(vars=_make_vars()))

    assert isinstance(result, ShotHook)
    assert result.hook_text == "你以为夜里失眠是缺觉？其实是它没到位"
    assert result.pattern_id == "conflict_001"
    assert result.pattern_type == "conflict"
    assert result.rationale and "反差" in result.rationale


# ---------------------------------------------------------------------------
# 2. format_output —— 严格路径
# ---------------------------------------------------------------------------


def test_format_output_handles_clean_json() -> None:
    """干净 JSON 直接走 ``model_validate_json`` 严格路径，无需 json-repair。"""
    agent = HookWriterAgent(_MockChatModel(_VALID_HOOK_JSON))

    result = agent.format_output(_VALID_HOOK_JSON)

    assert isinstance(result, ShotHook)
    assert result.pattern_type == "conflict"


# ---------------------------------------------------------------------------
# 3-4. format_output —— json-repair 兜底
# ---------------------------------------------------------------------------


def test_format_output_handles_unquoted_keys_via_json_repair() -> None:
    """未加引号的对象键名应被 json-repair 修复后再校验。"""
    raw = (
        "{hook_text:'你以为夜里失眠是缺觉？其实是它没到位',"
        "pattern_id:'conflict_001',pattern_type:'conflict',"
        "rationale:'用反差引发好奇'}"
    )
    agent = HookWriterAgent(_MockChatModel(raw))

    result = agent.format_output(raw)

    assert isinstance(result, ShotHook)
    assert result.pattern_id == "conflict_001"
    assert result.rationale == "用反差引发好奇"


def test_format_output_handles_trailing_comma_via_json_repair() -> None:
    """对象的尾逗号应被 json-repair 容错。"""
    raw = """{
        "hook_text": "你以为夜里失眠是缺觉？其实是它没到位",
        "pattern_id": "conflict_001",
        "pattern_type": "conflict",
        "rationale": "用反差引发好奇",
    }"""
    agent = HookWriterAgent(_MockChatModel(raw))

    result = agent.format_output(raw)

    assert isinstance(result, ShotHook)
    assert result.hook_text.startswith("你以为")


# ---------------------------------------------------------------------------
# 5-6. ShotHook Pydantic 长度边界
# ---------------------------------------------------------------------------


def test_hook_text_under_min_length_rejected_by_pydantic() -> None:
    """``hook_text`` ``min_length=4`` 校验：3 字符直接拒绝。"""
    with pytest.raises(ValidationError):
        ShotHook(
            hook_text="abc",
            pattern_id="p1",
            pattern_type="question",
            rationale=None,
        )


def test_hook_text_over_max_length_rejected_by_pydantic() -> None:
    """``hook_text`` ``max_length=80`` 校验：81 字符直接拒绝。"""
    with pytest.raises(ValidationError):
        ShotHook(
            hook_text="x" * 81,
            pattern_id="p1",
            pattern_type="question",
            rationale=None,
        )


# ---------------------------------------------------------------------------
# 7. pattern_id 必填
# ---------------------------------------------------------------------------


def test_pattern_id_required() -> None:
    """``pattern_id`` 缺失时 Pydantic 应拒绝。"""
    with pytest.raises(ValidationError):
        ShotHook(  # type: ignore[call-arg]
            hook_text="你试过这个吗",
            pattern_type="question",
            rationale=None,
        )


# ---------------------------------------------------------------------------
# 8-9. Agent 元数据
# ---------------------------------------------------------------------------


def test_agent_uses_json_schema_method() -> None:
    """D5 决策：HookWriterAgent 一律使用 json_schema strict。"""
    agent = HookWriterAgent(_MockChatModel(""))

    # pylint: disable=protected-access
    assert agent._structured_output_method == "json_schema"


def test_agent_inherits_correct_output_model() -> None:
    """``output_model`` 必须为 ``ShotHook``。"""
    agent = HookWriterAgent(_MockChatModel(""))

    assert agent.output_model is ShotHook


# ---------------------------------------------------------------------------
# 10. 模板变量映射：a_write_hook 正确把 HookWriteVars 拆分到 prompt
# ---------------------------------------------------------------------------


def test_a_write_hook_passes_vars_correctly() -> None:
    """``a_write_hook`` 应把 product_name / pain_points 注入渲染后的 prompt。"""
    mock = _MockChatModel(_VALID_HOOK_JSON)
    agent = HookWriterAgent(mock)

    asyncio.run(agent.a_write_hook(vars=_make_vars()))

    rendered = _rendered_prompt_text(mock)
    assert "conflict_001" in rendered
    assert "深睡褪黑素软糖" in rendered
    assert "夜里失眠" in rendered


# ---------------------------------------------------------------------------
# 11. 模板 input_variables 与 hook_pattern_writer_v1 对齐
# ---------------------------------------------------------------------------


def test_prompt_template_input_variables() -> None:
    """模板的输入变量应与 ``hook_pattern_writer_v1`` 一致：3 个变量。"""
    assert sorted(HOOK_WRITER_PROMPT.input_variables) == [
        "audience",
        "pattern_id",
        "product",
    ]
