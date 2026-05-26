"""DurationRewriterAgent — 把 dialog/narration 改写到指定字数上限以内
（P3 W17 T17-7 子组件）。

为何存在
--------

Decision F 决策树在 ``llm_rewrite`` 分支需要把过长的台词收缩到
``target_chars`` 个字符以内，让 TTS 合成时长落入镜头 ±15% 阈值。
本 Agent 把这件事固化成 ``json_schema`` 结构化输出，沿用 W3-T1 +
W4 commerce agents 的约定：

- ``method="json_schema"`` strict structured output；
- 提示词正文来自 ``builtin_prompts._DURATION_REWRITER`` 单一真相源；
- ``format_output`` 重写：先尝试严格 JSON 解析，再用 ``json-repair`` 兜底；
- ``a_rewrite_to_target`` 在拿到结果后强制兜底：如果 ``rewritten_text``
  仍然超过 ``target_chars``，由 Agent 截断并刷新 ``char_count``，
  保证下游 ``ChapterAvPlanner`` 不会基于错误字数继续决策。

为什么不放到 BUILTIN_PROMPT_DEFINITIONS：
    避免引入第 13 类 commerce 模板 / 新 PromptCategory，与既有 27 项
    snapshot 契约保持兼容；模板由模块级常量直接消费即可。
"""

# pylint: disable=redefined-builtin

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.chains.agents.base import AgentBase
from app.models.types import DialogueLineMode
from app.services.studio.builtin_prompts import _DURATION_REWRITER


# ---------------------------------------------------------------------------
# IO 契约
# ---------------------------------------------------------------------------


class DurationRewriteVars(BaseModel):
    """``DurationRewriterAgent.a_rewrite_to_target`` 的输入参数。

    字段:
        original_text: 待改写的原始台词；通常来自 ``ShotDialogLine.text``。
        target_chars: 改写后字数上限（≥ 1）；由 ``ChapterAvPlanner`` 根据
            ``shot.duration_sec`` × 速率推得。
        line_mode: 对白模式，决定下游模板里 DIALOGUE / VOICE_OVER 的语境；
            模板会用其大写值（如 "DIALOGUE"）渲染。
    """

    model_config = ConfigDict(extra="forbid")

    original_text: str = Field(..., description="原始台词（保留原始换行/标点）")
    target_chars: int = Field(..., ge=1, description="改写后字数上限")
    line_mode: DialogueLineMode = Field(
        default=DialogueLineMode.dialogue,
        description="对白模式（DIALOGUE / VOICE_OVER / OFF_SCREEN / PHONE）",
    )

    @field_validator("target_chars")
    @classmethod
    def _validate_target_chars_positive(cls, value: int) -> int:
        """``target_chars`` 必须 ≥ 1：0 / 负值无业务意义。"""

        if value < 1:
            raise ValueError("target_chars must be >= 1")
        return value


class DurationRewriteResult(BaseModel):
    """LLM 返回的结构化改写结果。

    字段:
        rewritten_text: 改写后的台词。
        char_count: ``rewritten_text`` 的字符数。Agent 会在 post-process
            阶段把它强制对齐到 ``len(rewritten_text)``，避免 LLM 自报漂移。
    """

    model_config = ConfigDict(extra="forbid")

    rewritten_text: str = Field(..., description="改写后的台词文本")
    char_count: int = Field(..., ge=0, description="rewritten_text 的字符数")


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT = (
    "你是 TTS 时长收敛改写器。\n"
    "目标：把输入台词改写为 ≤ target_chars 字符的版本，让 TTS 合成时长\n"
    "落入镜头允许的 ±15% 漂移区间，避免下游 chapter_av_planner 反复回灌。\n"
    "\n"
    "铁律：\n"
    "1. 输出字符数 ≤ target_chars；\n"
    "2. 必须保留原文关键信息（卖点 / 数字 / 行动指令）与情绪走向；\n"
    "3. 不新增原文未出现的事实 / 价格 / 品牌承诺；\n"
    "4. 禁用绝对化用语（最 / 第一 / 唯一 等）；\n"
    "5. 仅输出 JSON：{rewritten_text, char_count}，不要 Markdown 包裹。"
)


DURATION_REWRITE_PROMPT = PromptTemplate(
    input_variables=["original_text", "target_chars", "line_mode"],
    template=_DURATION_REWRITER,
    template_format="jinja2",
)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class DurationRewriterAgent(AgentBase[DurationRewriteResult]):
    """把台词改写到 ``target_chars`` 字数上限以内的 Agent。

    设计要点:
        - structured output method 固定为 ``"json_schema"``；
        - prompt 模板直接引用 ``builtin_prompts._DURATION_REWRITER``；
        - ``format_output`` 重写：严格 JSON → ``json-repair`` salvage → raise；
        - ``a_rewrite_to_target`` 在拿到 LLM 输出后做两层兜底：
            1. 把 ``DialogueLineMode`` 渲染为大写字符串（与提示词的
               枚举对齐）；
            2. 强制把 ``rewritten_text`` 截到 ``target_chars`` 以内，
               并把 ``char_count`` 与 ``len(rewritten_text)`` 对齐。
    """

    def __init__(
        self,
        model: BaseChatModel,
        *,
        agent_kwargs: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            model,
            structured_output_method="json_schema",
            agent_kwargs=agent_kwargs,
        )

    @property
    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    @property
    def prompt_template(self) -> PromptTemplate:
        return DURATION_REWRITE_PROMPT

    @property
    def output_model(self) -> type[DurationRewriteResult]:
        return DurationRewriteResult

    def format_output(self, raw: str) -> DurationRewriteResult:
        """将 LLM 原始输出解析为 ``DurationRewriteResult``。

        策略:
            1. 先尝试 ``DurationRewriteResult.model_validate_json``（严格 JSON）；
            2. 失败时使用 ``json-repair`` 修复常见偏差（unquoted key、trailing
               comma、Markdown 围栏等）后再次校验；
            3. 仍失败时抛 Pydantic ``ValidationError`` 由上层处理。
        """

        try:
            return DurationRewriteResult.model_validate_json(raw)
        except Exception:  # pylint: disable=broad-except
            # 延迟导入：仅在严格解析失败时才加载 json-repair，降低启动开销。
            from json_repair import repair_json  # pylint: disable=import-outside-toplevel

            repaired = repair_json(raw, return_objects=True, skip_json_loads=False)
            return DurationRewriteResult.model_validate(repaired)

    async def a_rewrite_to_target(
        self,
        *,
        vars: DurationRewriteVars,
    ) -> DurationRewriteResult:
        """异步入口：基于 ``DurationRewriteVars`` 输出 ≤ target_chars 字数的改写文本。

        流程:
            1. 把 ``DialogueLineMode`` 转成大写字符串（与提示词模板对齐）；
            2. ``aextract`` 优先走 structured output，失败时回退到
               ``arun + format_output``（json-repair salvage）；
            3. 字数硬约束兜底：若 ``rewritten_text`` 仍 > ``target_chars``，
               强制截断；同时把 ``char_count`` 与 ``len(rewritten_text)``
               对齐，避免下游基于错误字数继续决策。

        参数:
            vars: ``DurationRewriteVars`` 实例，封装改写所需上下文。

        返回:
            校验通过的 :class:`DurationRewriteResult` 实例。
        """

        result = await self.aextract(
            original_text=vars.original_text,
            target_chars=vars.target_chars,
            line_mode=vars.line_mode.value,
        )

        capped = self._cap_to_target_chars(
            text=result.rewritten_text, target_chars=vars.target_chars
        )
        if capped != result.rewritten_text:
            return DurationRewriteResult(
                rewritten_text=capped,
                char_count=len(capped),
            )
        if result.char_count != len(result.rewritten_text):
            return DurationRewriteResult(
                rewritten_text=result.rewritten_text,
                char_count=len(result.rewritten_text),
            )
        return result

    @staticmethod
    def _cap_to_target_chars(*, text: str, target_chars: int) -> str:
        """字数硬约束兜底：若 LLM 输出超长，按 ``target_chars`` 截断。

        简单按字符切片即可——本 Agent 的语义保留交给 LLM，超长截断只是
        防御性收尾，避免让下游 ``ChapterAvPlanner`` 又一次踩到字数超限。
        """

        if target_chars < 0:
            return ""
        if len(text) <= target_chars:
            return text
        return text[:target_chars]


__all__ = [
    "DURATION_REWRITE_PROMPT",
    "DurationRewriteResult",
    "DurationRewriteVars",
    "DurationRewriterAgent",
]
