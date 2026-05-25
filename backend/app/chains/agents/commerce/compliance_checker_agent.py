"""ComplianceCheckerAgent — 双引擎合规检查（规则引擎 + LLM 语义判断），合并产出 ComplianceReport。

为什么存在：
    剧情带货脚本在发布前必须做合规审查。单靠关键词扫描无法覆盖
    "暗示治疗效果""不可验证的极致宣称""隐性贬低同类"等灰区表达；
    单靠 LLM 又无法稳定保证黑名单关键词被命中（成本高、漏检、漂移）。
    本 agent 把两条通路合并：

        rule_engine.scan(...)   —— W3-T3 pyahocorasick 多模式精确匹配（O(N+L) 线性扫描）
        +
        LLM 语义检查           —— LangChain ``json_schema`` structured output，
                                  从语义/语用层补全规则覆盖不到的隐含违规

    最后用 :meth:`ComplianceCheckerAgent.merge_findings` 做去重与严重等级
    取大，再以简单经验公式打分，产出 :class:`ComplianceReport`。

设计要点：
    1. **规则引擎**：默认装载 ``CN_MAINLAND_RULES``（8 条），
       可在构造时注入自定义引擎用于测试或多地域；
    2. **LLM 部分**：复用 ``compliance_checker_v1`` 系统级提示词
       （:mod:`app.services.studio.builtin_prompts`）；
    3. **合并策略**：union(规则 findings, LLM findings)，按
       ``(rule_id, location)`` 去重；同键命中时严重等级取较高者
       （blocker > warning > info）；
    4. **评分公式**：``100 - 25*blockers - 5*warnings - 1*infos``，
       下限 0，上限 100。

输入：
    script_text (str), region (ComplianceRegion), product_category (ProductCategory),
    script_duration_sec (int), brand_aliases (tuple[str, ...]).

输出：
    :class:`ComplianceReport`（``findings`` + ``score`` 0-100 + ``summary``）。
"""

from __future__ import annotations

from typing import Any, ClassVar, cast

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import PromptTemplate

from app.chains.agents.base import AgentBase
from app.core.contracts.story import ComplianceFinding, ComplianceReport
from app.models.types import ComplianceRegion, ProductCategory
from app.services.compliance.builtin_rules import CN_MAINLAND_RULES
from app.services.compliance.rule_engine import (
    ComplianceFindingDTO,
    ComplianceRuleEngine,
)
from app.services.studio.builtin_prompts import BUILTIN_PROMPT_DEFINITIONS

_TEMPLATE_ID = "compliance_checker_v1"


def _get_builtin_template_content(template_id: str) -> str:
    """从 :data:`BUILTIN_PROMPT_DEFINITIONS` 检索指定提示词的 Jinja2 正文。

    单一真相源策略：合规检查的提示词由 W3-T1 入库，本 agent 不复制
    一份本地副本，避免提示词漂移。

    Args:
        template_id: 提示词主键（命名约定 ``<category_value>_v1``）。

    Returns:
        Jinja2 模板字符串原文。

    Raises:
        KeyError: 提示词注册表中不存在该 id（通常意味着启动期 bootstrap 漏写）。
    """

    for definition in BUILTIN_PROMPT_DEFINITIONS:
        if definition.id == template_id:
            return definition.template_content
    raise KeyError(f"builtin prompt not found: {template_id}")


_SYSTEM_PROMPT = """你是中国大陆短视频广告合规审核员。
任务：从语义层面识别脚本中可能违反广告法/平台规则的隐含表达——这些表达不会被关键词扫描器命中，但仍构成风险。

聚焦场景：
- 暗示医疗/治疗效果（"重塑""逆龄""根除"等转义说法）
- 不可验证的极致宣称（"行业第一""效果100%"）
- 隐性贬低同类（"市面上其他...都是骗局"）
- 易引发地域/性别/职业群体不满的表达

输出严格的 ComplianceReport JSON，每条 finding 必须给 location（如"Shot 3 dialog"）和 suggested_fix（中文）。
"""


# 注意：``compliance_checker_v1`` 模板使用 Jinja2 ``{{ var }}`` 占位，
# 因此必须显式声明 ``template_format="jinja2"``，否则默认 f-string 模式会
# 把 ``{{ script }}`` 当作字面 ``{ script }`` 处理，变量不会被替换。
COMPLIANCE_CHECKER_PROMPT = PromptTemplate(
    input_variables=["script", "region", "product_category"],
    template=_get_builtin_template_content(_TEMPLATE_ID),
    template_format="jinja2",
)


# 严重等级排序（数值越大越严重）。
# 用 ClassVar 暴露给上层在合并/排序时可复用，避免散落的字典字面量。
_SEVERITY_RANK: dict[str, int] = {"blocker": 3, "warning": 2, "info": 1}


class ComplianceCheckerAgent(AgentBase[ComplianceReport]):
    """合规双引擎检查器：规则引擎（W3-T3）+ LLM 语义检查的融合 agent。"""

    # 评分扣分系数（每出现一次扣多少分）。集中放这里便于调参。
    SCORE_DEDUCTION: ClassVar[dict[str, int]] = {
        "blocker": 25,
        "warning": 5,
        "info": 1,
    }

    def __init__(
        self,
        model: BaseChatModel,
        *,
        agent_kwargs: dict[str, object] | None = None,
        rule_engine: ComplianceRuleEngine | None = None,
    ) -> None:
        """构造 agent。

        Args:
            model: LangChain ``BaseChatModel`` 实例（OpenAI / DashScope 均可）。
            agent_kwargs: 透传给 :class:`AgentBase` 的 ``agent_kwargs``。
            rule_engine: 可注入的规则引擎；默认使用 ``CN_MAINLAND_RULES`` 8 条规则。
                测试或多地域场景可传入自定义引擎以替换规则集。
        """

        super().__init__(
            model,
            structured_output_method="json_schema",
            agent_kwargs=cast(dict[str, Any] | None, agent_kwargs),
        )
        self._rule_engine = rule_engine or ComplianceRuleEngine(CN_MAINLAND_RULES)

    # ------------------------------------------------------------------
    # AgentBase 必需的抽象属性
    # ------------------------------------------------------------------

    @property
    def system_prompt(self) -> str:
        """系统提示词：聚焦 LLM 在语义层兜住关键词扫不到的风险表达。"""

        return _SYSTEM_PROMPT

    @property
    def prompt_template(self) -> PromptTemplate:
        """LLM 输入提示词模板（Jinja2，来自 :data:`BUILTIN_PROMPT_DEFINITIONS`）。"""

        return COMPLIANCE_CHECKER_PROMPT

    @property
    def output_model(self) -> type[ComplianceReport]:
        """LLM 结构化输出契约：:class:`ComplianceReport`。"""

        return ComplianceReport

    # ------------------------------------------------------------------
    # 输出解析
    # ------------------------------------------------------------------

    def format_output(self, raw: str) -> ComplianceReport:
        """把 LLM 原始输出解析为 :class:`ComplianceReport`。

        步骤：
            1. 优先 :meth:`ComplianceReport.model_validate_json` 直接解析；
            2. 失败时调用 ``json_repair.repair_json`` 修复常见 JSON 噪声
               （多余引号、未引号键、单引号、末尾逗号等），再走 dict
               校验路径。

        Args:
            raw: LLM 原始字符串输出（可能含 ``\\n`` / 多余字符）。

        Returns:
            校验通过的 :class:`ComplianceReport` 实例。
        """

        try:
            return ComplianceReport.model_validate_json(raw)
        except Exception:  # pylint: disable=broad-except
            from json_repair import repair_json  # 局部导入避免冷启动开销
            repaired = repair_json(
                raw,
                return_objects=True,
                skip_json_loads=False,
            )
            return ComplianceReport.model_validate(repaired)

    # ------------------------------------------------------------------
    # 合并 / 评分 / 摘要 —— 纯函数，便于单测
    # ------------------------------------------------------------------

    @staticmethod
    def merge_findings(
        rule_findings: list[ComplianceFindingDTO],
        llm_findings: list[ComplianceFinding],
    ) -> list[ComplianceFinding]:
        """合并规则引擎与 LLM 产出的 findings。

        合并规则：
            - 以 ``(rule_id, location)`` 为去重键；
            - 命中同键时，严重等级取较高者（blocker > warning > info），
              其它字段沿用先到的版本（具体取胜方由严重等级决定）。

        Args:
            rule_findings: 规则引擎产出的 :class:`ComplianceFindingDTO` 列表。
            llm_findings: LLM 产出的 :class:`ComplianceFinding` 列表。

        Returns:
            合并后的 :class:`ComplianceFinding` 列表，保持稳定顺序：
            先规则引擎条目，后 LLM 新增条目。
        """

        merged: dict[tuple[str, str | None], ComplianceFinding] = {}

        # 规则引擎 DTO 转换为 Pydantic ComplianceFinding；
        # severity 是 ComplianceSeverity 枚举，用 .value 转字符串以匹配 Literal。
        for rule_finding in rule_findings:
            key = (rule_finding.rule_id, rule_finding.location)
            merged[key] = ComplianceFinding(
                rule_id=rule_finding.rule_id,
                rule_kind=rule_finding.rule_kind,  # type: ignore[arg-type]
                severity=rule_finding.severity.value,  # type: ignore[arg-type]
                description=rule_finding.description,
                location=rule_finding.location,
                suggested_fix=rule_finding.suggested_fix,
            )

        for llm_finding in llm_findings:
            key = (llm_finding.rule_id, llm_finding.location)
            existing = merged.get(key)
            if existing is None:
                merged[key] = llm_finding
                continue
            # 同键冲突：严重等级取较高者。
            if _SEVERITY_RANK.get(llm_finding.severity, 0) > _SEVERITY_RANK.get(
                existing.severity, 0
            ):
                merged[key] = llm_finding

        return list(merged.values())

    @classmethod
    def calculate_score(cls, findings: list[ComplianceFinding]) -> int:
        """以经验公式从 findings 推导合规得分。

        公式：``score = 100 - 25*blockers - 5*warnings - 1*infos``，
        最终值 clamp 到 ``[0, 100]``。

        Args:
            findings: 合并后的合规问题列表。

        Returns:
            ``[0, 100]`` 内的整数得分。
        """

        deduction = 0
        for finding in findings:
            deduction += cls.SCORE_DEDUCTION.get(finding.severity, 0)
        return max(0, 100 - deduction)

    @staticmethod
    def _build_summary(findings: list[ComplianceFinding]) -> str:
        """根据 findings 严重等级分布生成中文摘要文本。

        - 全空 → "未发现合规风险。"
        - 否则 → "发现 X 个阻断项 / Y 个警告 / Z 个提示。"

        摘要刻意保持简短（≤30 字），便于直接展示在前端 banner / 任务中心。
        """

        if not findings:
            return "未发现合规风险。"
        blockers = sum(1 for finding in findings if finding.severity == "blocker")
        warnings = sum(1 for finding in findings if finding.severity == "warning")
        infos = sum(1 for finding in findings if finding.severity == "info")
        return f"发现 {blockers} 个阻断项 / {warnings} 个警告 / {infos} 个提示。"

    # ------------------------------------------------------------------
    # 对外异步入口
    # ------------------------------------------------------------------

    async def a_check(
        self,
        *,
        script_text: str,
        region: ComplianceRegion,
        product_category: ProductCategory,
        script_duration_sec: int = 60,
        brand_aliases: tuple[str, ...] = (),
    ) -> ComplianceReport:
        """异步执行双引擎合规检查并返回合并报告。

        执行步骤：
            1. 规则引擎按地区/品类扫描脚本，得到 :class:`ComplianceFindingDTO` 列表；
            2. 调用 LLM 做语义层 :class:`ComplianceReport` 结构化产出；
            3. :meth:`merge_findings` 合并；:meth:`calculate_score` 评分；
               :meth:`_build_summary` 生成摘要文本。

        Args:
            script_text: 待审脚本/字幕原文。
            region: 目标合规地区（``cn_mainland`` / ``hk_tw`` / ``overseas``）。
            product_category: 商品品类；驱动 ``required_disclaimer`` 是否启用。
            script_duration_sec: 脚本时长（秒），影响 brand cap 阈值线性外推。
            brand_aliases: 当前项目品牌词表；空元组时跳过 brand cap 规则。

        Returns:
            汇总后的 :class:`ComplianceReport`，``variant_id`` 为 None
            （落库前预校验场景）。
        """

        # 1. 规则引擎：精确匹配优先，O(N+L) 线性扫描。
        rule_findings = self._rule_engine.scan(
            script_text,
            region=region,
            product_category=product_category,
            script_duration_sec=script_duration_sec,
            # P1 静态规则的 brand_aliases 默认为空，由调用方按项目注入；
            # 空元组等价于"未注入"，这里显式映射成 None 以走规则自身默认。
            brand_aliases_override=brand_aliases or None,
        )

        # 2. LLM：语义/语用层兜底，提示词内含 JSON schema 引导。
        llm_report = await self.aextract(
            script=script_text,
            region=region.value,
            product_category=product_category.value,
        )

        # 3. 合并 + 评分 + 摘要。
        merged = self.merge_findings(rule_findings, llm_report.findings)
        score = self.calculate_score(merged)
        summary = self._build_summary(merged)

        return ComplianceReport(
            variant_id=None,
            region=region.value,
            product_category=product_category.value,
            findings=merged,
            score=score,
            summary=summary,
        )


__all__ = [
    "COMPLIANCE_CHECKER_PROMPT",
    "ComplianceCheckerAgent",
]
