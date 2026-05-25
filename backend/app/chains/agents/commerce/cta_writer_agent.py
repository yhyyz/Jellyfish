"""CTAWriterAgent — 按 cta_pattern + hardness + urgency_type 生成结尾 CTA 文案。

输入：
    - ``vars`` (``CTAWriteVars``)：上游已选定的 ``pattern_id``、硬度、紧迫感
      类型，以及商品基本信息与目标动作。

输出：
    - ``CTAText`` Pydantic 模型（来自 ``app.core.contracts.story``）。

设计要点（与同 Wave 的 ``ProductExtractorAgent`` 保持一致）：

1. 使用 ``method="json_schema"`` strict 的 structured output（D5 决策），
   相比 function_calling 在 ``hardness`` / ``urgency_type`` 等枚举回填上更可靠；
2. 提示词正文直接来自 W3-T1 的 ``BUILTIN_PROMPT_DEFINITIONS``
   （``cta_pattern_writer_v1``），单一真相源、避免漂移；
3. ``format_output`` 重写：先尝试严格 JSON 解析，失败时使用 ``json-repair``
   兜底，容忍 LLM 常见的 unquoted key / trailing comma / Python 字面量等偏差；
4. 接口形状参照 ``ProductExtractorAgent``，公开 ``a_write_cta`` 异步入口；
5. ``cta_pattern_writer_v1`` 模板的 ``input_variables`` 为
   ``["hardness", "product", "urgency_type"]``，故将 ``pattern_id`` /
   ``product_name`` 等额外上下文打包进 ``product`` 文本注入提示词，
   并通过系统提示词要求 LLM 在输出中回填 ``pattern_id`` / ``hardness`` /
   ``urgency_type``，避免修改既有模板。
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import PromptTemplate

from app.chains.agents.base import AgentBase
from app.core.contracts.story import CTAText, CTAWriteVars
from app.services.studio.builtin_prompts import BUILTIN_PROMPT_DEFINITIONS

_TEMPLATE_ID = "cta_pattern_writer_v1"


def _get_builtin_template_content(template_id: str) -> str:
    """从 W3-T1 注册表读取模板正文（单一真相源）。

    存在原因：
        避免在 Agent 文件里复制一份 prompt 文本，防止 W3-T1 与 W12-T2 间出现漂移。

    参数:
        template_id: ``BUILTIN_PROMPT_DEFINITIONS`` 中模板的 ``id``，
            例如 ``"cta_pattern_writer_v1"``。

    返回:
        Jinja2 模板源字符串。

    异常:
        当 ``template_id`` 在注册表中不存在时抛出 ``KeyError``，
        防止静默回退到错误模板。
    """
    for definition in BUILTIN_PROMPT_DEFINITIONS:
        if definition.id == template_id:
            return definition.template_content
    raise KeyError(f"builtin prompt not found: {template_id}")


_SYSTEM_PROMPT = (
    "你是中文短视频 CTA（行动号召）撰写专家。\n"
    "任务：根据 hardness + urgency_type + 商品信息，输出严格符合 CTAText schema 的 JSON。\n"
    "\n"
    "铁律：\n"
    "1. cta_text 必须包含明确动作（加购/下单/关注/试用）\n"
    "2. hardness 决定语气强度：soft 友好邀请 / medium 平衡 / hard 强促销\n"
    "3. urgency_type 决定文案策略：\n"
    "   - scarcity：限量\n"
    "   - urgency：限时\n"
    "   - social_proof：人气\n"
    "   - benefit：利益直击\n"
    "   - risk_removal：消除顾虑\n"
    "4. cta_text ≤ 60 字（约 5 秒可读）\n"
    "5. 不夸大、不虚假宣称（合规友好）\n"
    "\n"
    "只输出 JSON。\n"
    "输出 JSON 必须回填上游传入的 pattern_id / hardness / urgency_type 原值，"
    "不得擅自更换。"
)


CTA_WRITER_PROMPT = PromptTemplate(
    input_variables=["hardness", "product", "urgency_type"],
    template=_get_builtin_template_content(_TEMPLATE_ID),
    template_format="jinja2",
)


def _format_product_block(vars_: CTAWriteVars) -> str:
    """把 ``CTAWriteVars`` 中商品/动作/pattern 字段拼装为提示词中的 product 文本。

    存在原因：
        ``cta_pattern_writer_v1`` 模板的输入变量固定为
        ``["hardness", "product", "urgency_type"]``，且本任务约定不修改该模板，
        故把 ``pattern_id`` / ``product_name`` / ``product_url`` /
        ``discount_text`` / ``target_action`` 等额外上下文统一序列化进 ``product``
        段落，便于 LLM 在文案中精准引用并在输出 JSON 中回填 ``pattern_id``。

    参数:
        vars_: 上游传入的 ``CTAWriteVars`` 实例。

    返回:
        多行文本，每行一个键值对，便于 LLM 按结构理解。
    """
    return (
        f"name: {vars_.product_name}\n"
        f"url: {vars_.product_url or '未提供'}\n"
        f"discount: {vars_.discount_text or '未提供'}\n"
        f"target_action: {vars_.target_action}\n"
        f"pattern_id: {vars_.pattern_id}"
    )


class CTAWriterAgent(AgentBase[CTAText]):
    """结尾 CTA 文案撰写 Agent。

    职责：
        基于上游已选定的 ``pattern_id`` / ``hardness`` / ``urgency_type`` 与
        商品上下文，生成一条符合 ``CTAText`` 契约的中文 CTA 文案，供短视频
        脚本结尾镜头与素材库消费。

    关键设计：
        - structured output method 固定为 ``"json_schema"``（D5 决策）；
        - prompt 模板来自 W3-T1 的 ``cta_pattern_writer_v1``，本 Agent 不修改；
        - ``format_output`` 重写：严格 JSON 解析失败时使用 ``json-repair`` 兜底；
        - ``a_write_cta`` 入口接收 ``CTAWriteVars``，内部组装 ``product`` 段落
          后调用 ``aextract``，避免暴露模板细节给上游。
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
        return CTA_WRITER_PROMPT

    @property
    def output_model(self) -> type[CTAText]:
        return CTAText

    def format_output(self, raw: str) -> CTAText:
        """将 LLM 原始输出解析为 ``CTAText``。

        策略：
            1. 先尝试 ``CTAText.model_validate_json``（严格 JSON）；
            2. 失败时使用 ``json-repair`` 修复常见偏差（unquoted key、trailing
               comma、Python 字面量等）后再次校验。
            两次都失败时抛出 Pydantic ``ValidationError``，由上层调用方处理。

        参数:
            raw: LLM 原始字符串输出，期望为 JSON 文本。

        返回:
            校验通过的 ``CTAText`` 实例。
        """
        try:
            return CTAText.model_validate_json(raw)
        except Exception:  # pylint: disable=broad-except
            from json_repair import repair_json  # pylint: disable=import-outside-toplevel

            repaired = repair_json(
                raw,
                return_objects=True,
                skip_json_loads=False,
            )
            return CTAText.model_validate(repaired)

    async def a_write_cta(  # pylint: disable=redefined-builtin
        self,
        *,
        vars: CTAWriteVars,
    ) -> CTAText:
        """异步入口：基于 ``CTAWriteVars`` 生成 ``CTAText``。

        参数:
            vars: 上游已就绪的输入上下文，包括所选 ``pattern_id``、硬度、
                紧迫感类型、商品基本信息与目标动作。

        返回:
            校验通过的 ``CTAText`` 实例。
        """
        product_text = _format_product_block(vars)
        return await self.aextract(
            hardness=vars.hardness,
            product=product_text,
            urgency_type=vars.urgency_type,
        )
