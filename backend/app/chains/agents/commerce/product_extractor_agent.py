"""ProductExtractorAgent — 从商品页文本/URL 提取结构化商品信息。

输入：
    - ``raw_text`` (str)：商品页粘贴文本或 URL。
    - ``target_fields`` (list[str] | None)：期望抽取的字段列表，为空时让 LLM 抽全部字段。

输出：
    - ``ProductExtractionResult`` Pydantic 模型（来自 ``app.core.contracts.story``）。

设计要点（详见 ``.omo/notepads/jellyfish-story-commerce/decisions.md`` D5）：

1. 使用 ``method="json_schema"`` strict 的 structured output，
   相比 function_calling 在嵌套字段（如 ``target_audience``）上更可靠。
2. 提示词正文直接来自 W3-T1 的 ``BUILTIN_PROMPT_DEFINITIONS``（单一真相源），
   避免重复维护两套相同模板。
3. ``format_output`` 重写：先尝试严格 JSON 解析，失败时使用 ``json-repair``
   兜底，容忍 LLM 常见的 unquoted key / trailing comma / Python 字面量等偏差。
4. 接口形状参照现有 ``PropInfoAnalysisAgent``，保持与既有 Agent 一致的 ``aextract``
   入口契约。
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import PromptTemplate

from app.chains.agents.base import AgentBase
from app.core.contracts.story import ProductExtractionResult
from app.services.studio.builtin_prompts import BUILTIN_PROMPT_DEFINITIONS

_TEMPLATE_ID = "product_extraction_v1"


def _get_builtin_template_content(template_id: str) -> str:
    """从 W3-T1 注册表读取模板正文（单一真相源）。

    存在原因：
        避免在 Agent 文件里复制一份 prompt 文本，防止 W3-T1 与 W4-T1 间出现漂移。

    参数:
        template_id: ``BUILTIN_PROMPT_DEFINITIONS`` 中模板的 ``id``，
            例如 ``"product_extraction_v1"``。

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
    "你是商品信息抽取助手。输入是商品页文本或链接，输出严格符合 "
    "ProductExtractionResult schema 的 JSON。\n"
    "关键约束：selling_points 最多 5 个；pain_points_solved 最多 5 个；"
    "name/description 必填；竞品名只填明确出现的，不臆造。"
)


# 用户提示词模板：直接复用 W3-T1 注册的 jinja2 模板正文，确保内容单一来源。
PRODUCT_EXTRACTION_PROMPT = PromptTemplate(
    input_variables=["raw_text", "target_fields"],
    template=_get_builtin_template_content(_TEMPLATE_ID),
    template_format="jinja2",
)


class ProductExtractorAgent(AgentBase[ProductExtractionResult]):
    """商品信息抽取 Agent。

    职责：
        从商品物料文本（商详页、详情图 OCR、营销文案、客服对话等）抽取
        结构化的 ``ProductExtractionResult``，供脚本生成与合规校验使用。

    关键设计：
        - structured output method 固定为 ``"json_schema"``（D5 决策），
          下游 Provider 在支持 strict 的情况下会启用最严格的 schema 校验；
        - prompt 模板直接引用 W3-T1 ``BUILTIN_PROMPT_DEFINITIONS``；
        - ``format_output`` 重写：严格 JSON 解析失败时使用 ``json-repair`` 兜底。
    """

    def __init__(
        self,
        model: BaseChatModel,
        *,
        agent_kwargs: dict[str, Any] | None = None,
    ) -> None:
        # D5：商品/脚本/合规三个新 commerce agent 一律使用 json_schema strict。
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
        return PRODUCT_EXTRACTION_PROMPT

    @property
    def output_model(self) -> type[ProductExtractionResult]:
        return ProductExtractionResult

    def format_output(self, raw: str) -> ProductExtractionResult:
        """将 LLM 原始输出解析为 ``ProductExtractionResult``。

        策略：
            1. 先尝试 ``ProductExtractionResult.model_validate_json``（严格 JSON）；
            2. 失败时使用 ``json-repair`` 修复常见偏差（unquoted key、trailing
               comma、Python 字面量等）后再次校验。
            两次都失败时抛出 Pydantic ``ValidationError``，由上层调用方处理。

        参数:
            raw: LLM 原始字符串输出，期望为 JSON 文本。

        返回:
            校验通过的 ``ProductExtractionResult`` 实例。
        """
        try:
            return ProductExtractionResult.model_validate_json(raw)
        except Exception:  # pylint: disable=broad-except
            # 延迟导入：仅在严格解析失败时加载 json-repair，避免无谓启动开销。
            from json_repair import repair_json  # pylint: disable=import-outside-toplevel

            repaired = repair_json(
                raw,
                return_objects=True,
                skip_json_loads=False,
            )
            return ProductExtractionResult.model_validate(repaired)

    async def a_extract_product(
        self,
        *,
        raw_text: str,
        target_fields: list[str] | None = None,
    ) -> ProductExtractionResult:
        """异步入口：从原始商品物料文本抽取 ``ProductExtractionResult``。

        参数:
            raw_text: 商品物料原文（商详页、详情图 OCR、营销文案等）。
            target_fields: 期望抽取的字段名清单；为空时让 LLM 抽全部字段，
                字段会以逗号拼接形式注入到 prompt 模板的 ``target_fields`` 变量。

        返回:
            校验通过的 ``ProductExtractionResult`` 实例。
        """
        fields_text = ", ".join(target_fields) if target_fields else "全部字段"
        return await self.aextract(raw_text=raw_text, target_fields=fields_text)
