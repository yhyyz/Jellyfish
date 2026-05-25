"""HookWriterAgent —— 生成前 3 秒钩子文本。

输入：
    - ``HookWriteVars``：``pattern_id`` + ``pattern_type`` + product/audience 上下文。

输出：
    - ``ShotHook``：含 ``hook_text`` / ``pattern_id`` / ``pattern_type`` / ``rationale``。

设计要点：

1. 走 ``method="json_schema"`` strict 的 structured output（D5），与
   W4 三个 commerce agent 保持一致。
2. 提示词正文直接来自 W3-T1 的 ``BUILTIN_PROMPT_DEFINITIONS``
   （``hook_pattern_writer_v1``），单一真相源。该模板暴露 3 个变量：
   ``pattern_id`` / ``product`` / ``audience``；``HookWriteVars`` 在 Agent
   入口拆分得更细，由本类合成模板所需结构。
3. ``format_output`` 重写：先严格 JSON 解析，失败时 ``json-repair`` 兜底。
4. 适用范围：``StoryScript.opening_hook`` 字段单独优化（generator 已生成
   基础钩子，本 Agent 用于 A/B 测试或 refinement）。
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import PromptTemplate

from app.chains.agents.base import AgentBase
from app.core.contracts.story import HookWriteVars, ShotHook
from app.services.studio.builtin_prompts import BUILTIN_PROMPT_DEFINITIONS

_TEMPLATE_ID = "hook_pattern_writer_v1"


def _get_builtin_template_content(template_id: str) -> str:
    """从 W3-T1 注册表读取模板正文（单一真相源）。

    存在原因：
        避免在 Agent 文件里复制一份 prompt 文本，防止 W3-T1 与本 Agent
        间出现漂移；未命中 id 时立即 ``KeyError`` 而非静默回退。

    参数:
        template_id: ``BUILTIN_PROMPT_DEFINITIONS`` 中模板的 ``id``。

    返回:
        Jinja2 模板正文字符串。

    异常:
        ``KeyError``：当 ``template_id`` 不存在于注册表时抛出。
    """
    for definition in BUILTIN_PROMPT_DEFINITIONS:
        if definition.id == template_id:
            return definition.template_content
    raise KeyError(f"builtin prompt not found: {template_id}")


_SYSTEM_PROMPT = """你是中文短视频钩子撰写专家。
任务：根据指定 hook 模式 + 商品 + 受众，输出严格符合 ShotHook schema 的 JSON。

铁律：
1. hook_text 必须中文，可读时间 < 3 秒（约 30 字内）。
2. pattern_type 必须与 pattern_id 自然映射（question / conflict / contrast /
   numerical / curiosity / shock / relatable / dialogue / visual / pov 之一）。
3. 不直接写商品名（除非 pattern 要求），否则破坏自然引入。
4. rationale 简要解释为什么本钩子能 work。

只输出 JSON，不要任何 Markdown 包裹。"""


HOOK_WRITER_PROMPT = PromptTemplate(
    input_variables=["pattern_id", "product", "audience"],
    template=_get_builtin_template_content(_TEMPLATE_ID),
    template_format="jinja2",
)


class HookWriterAgent(AgentBase[ShotHook]):
    """钩子撰写 Agent —— 输入 hook_pattern + product + audience，输出 ShotHook。

    职责：
        驱动 LLM 生成符合 ``ShotHook`` schema 的中文 3 秒钩子，供分镜
        ``opening_hook`` 字段的 A/B 测试与 refinement 流程消费。

    关键设计：
        - structured output method 固定为 ``"json_schema"``（D5）；
        - prompt 模板直接引用 W3-T1 ``BUILTIN_PROMPT_DEFINITIONS``；
        - ``format_output`` 重写：严格 JSON → ``json-repair`` salvage → raise；
        - ``a_write_hook`` 在入口处把 ``HookWriteVars`` 拆分映射到模板变量。
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
        return HOOK_WRITER_PROMPT

    @property
    def output_model(self) -> type[ShotHook]:
        return ShotHook

    def format_output(self, raw: str) -> ShotHook:
        """将 LLM 原始输出解析为 ``ShotHook``。

        策略：
            1. 先尝试 ``ShotHook.model_validate_json``（严格 JSON）；
            2. 失败时使用 ``json-repair`` 修复常见偏差（unquoted key /
               trailing comma / Python 字面量等）后再次校验；
            3. 两次都失败则抛出原始 Pydantic 异常，由上层处理。

        参数:
            raw: LLM 原始字符串输出，期望为 JSON 文本。

        返回:
            校验通过的 ``ShotHook`` 实例。
        """
        try:
            return ShotHook.model_validate_json(raw)
        except Exception:  # pylint: disable=broad-except
            from json_repair import repair_json  # pylint: disable=import-outside-toplevel

            repaired = repair_json(
                raw,
                return_objects=True,
                skip_json_loads=False,
            )
            return ShotHook.model_validate(repaired)

    @staticmethod
    def _compose_template_vars(vars_: HookWriteVars) -> dict[str, Any]:
        """把 ``HookWriteVars`` 映射成 ``hook_pattern_writer_v1`` 的模板变量。

        模板暴露 ``pattern_id`` / ``product`` / ``audience`` 三个变量，
        但 ``HookWriteVars`` 在入口处拆得更细，本方法承担合成职责：

        - ``product`` 字段聚合 ``product_name`` + ``product_description``；
        - ``audience`` 字段聚合 ``audience_pain_points`` + ``audience_demographics``。

        ``pattern_type`` 不出现在模板里，但保留在 ``HookWriteVars`` 中用于
        与 ``ShotHook.pattern_type`` 输出做契约对照。
        """
        product = {
            "name": vars_.product_name,
            "description": vars_.product_description,
        }
        audience = {
            "pain_points": list(vars_.audience_pain_points),
            "demographics": dict(vars_.audience_demographics),
        }
        return {
            "pattern_id": vars_.pattern_id,
            "product": product,
            "audience": audience,
        }

    async def a_write_hook(
        self,
        *,
        vars: HookWriteVars,  # pylint: disable=redefined-builtin
    ) -> ShotHook:
        """异步入口：根据 ``HookWriteVars`` 生成 ``ShotHook``。

        流程：
            1. 通过 ``_compose_template_vars`` 把入参拆分映射到模板变量；
            2. 走 ``aextract``：优先 structured output，失败时回退到
               ``arun + format_output``（json-repair salvage）。

        参数:
            vars: ``HookWriteVars`` 实例，封装 prompt 渲染所需上下文。

        返回:
            校验通过的 ``ShotHook`` 实例。
        """
        kwargs = self._compose_template_vars(vars)
        return await self.aextract(**kwargs)
