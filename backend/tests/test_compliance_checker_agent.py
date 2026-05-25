"""ComplianceCheckerAgent 解析 + 合并 + 评分 + 摘要回归测试（W4-T3）。

测试策略：
    - LLM 部分用 ``_MockChatModel`` 返回预设的 :class:`ComplianceReport` JSON；
    - 规则引擎部分使用 **真实** 的 :class:`ComplianceRuleEngine` + 默认 8 条
      ``CN_MAINLAND_RULES``；这正是 W4-T3 的集成价值所在；
    - 部分用例（merge / score / summary）走纯函数 API，避免重复跑 LLM。
"""

# pylint: disable=protected-access,too-few-public-methods

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.chains.agents.commerce.compliance_checker_agent import (
    ComplianceCheckerAgent,
)
from app.core.contracts.story import ComplianceFinding, ComplianceReport
from app.models.types import ComplianceRegion, ComplianceSeverity, ProductCategory
from app.services.compliance.builtin_rules import CN_MAINLAND_RULES
from app.services.compliance.rule_engine import (
    ComplianceFindingDTO,
    ComplianceRuleEngine,
)


# ---------------------------------------------------------------------------
# 测试夹具
# ---------------------------------------------------------------------------


class _MockChatModel(BaseChatModel):
    """最小化 LangChain ``BaseChatModel`` 模拟实现：恒定返回单一字符串。"""

    def __init__(self, response: str) -> None:
        super().__init__()
        self._response = response

    @property
    def _llm_type(self) -> str:  # pragma: no cover
        return "mock-compliance-chat-model"

    def _generate(  # type: ignore[override]
        self,
        messages: Any,  # pylint: disable=unused-argument
        stop: Any = None,  # pylint: disable=unused-argument
        run_manager: Any = None,  # pylint: disable=unused-argument
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=self._response))]
        )


def _empty_llm_report_json(
    region: str = "cn_mainland",
    product_category: str = "other",
) -> str:
    """构造一个"LLM 未发现风险"的 ComplianceReport JSON 字符串。"""

    return json.dumps(
        {
            "variant_id": None,
            "region": region,
            "product_category": product_category,
            "findings": [],
            "score": 100,
            "summary": "未发现合规风险。",
        }
    )


def _llm_report_json(
    findings: list[dict[str, Any]],
    region: str = "cn_mainland",
    product_category: str = "other",
) -> str:
    """构造一个携带任意 findings 的 ComplianceReport JSON 字符串。"""

    return json.dumps(
        {
            "variant_id": None,
            "region": region,
            "product_category": product_category,
            "findings": findings,
            "score": 50,
            "summary": "存在风险",
        }
    )


# 一段必然合规的脚本：包含演绎标识、健康类免责、且无任何黑名单词。
_CLEAN_SCRIPT = (
    "本视频为剧情演绎，产品功效因人而异，非医疗器械。"
    "今天我们分享一款好用的产品，欢迎评论区告诉我们你的真实想法。"
)


# ---------------------------------------------------------------------------
# 1. a_check 主流程
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_check_returns_compliance_report() -> None:
    """clean script + LLM empty findings → score=100 + 摘要为"未发现合规风险"。"""

    agent = ComplianceCheckerAgent(
        _MockChatModel(_empty_llm_report_json("cn_mainland", "health"))
    )

    report = await agent.a_check(
        script_text=_CLEAN_SCRIPT,
        region=ComplianceRegion.cn_mainland,
        product_category=ProductCategory.health,
    )

    assert isinstance(report, ComplianceReport)
    assert report.findings == []
    assert report.score == 100
    assert report.summary == "未发现合规风险。"
    assert report.region == "cn_mainland"
    assert report.product_category == "health"
    assert report.variant_id is None


@pytest.mark.asyncio
async def test_a_check_merges_rule_and_llm_findings() -> None:
    """脚本触发规则引擎 yanyi 缺失 + LLM 报另一条语义违规 → 合并报告含两条。"""

    # 这段脚本不含 演绎/虚构 → 必然触发 cn_yanyi_label（blocker）。
    script = "今天介绍一款好产品。"
    llm_finding = {
        "rule_id": "llm_semantic_overclaim",
        "rule_kind": "banned_phrase",
        "severity": "warning",
        "description": "疑似不可验证的极致宣称",
        "location": "Shot 1 dialog",
        "suggested_fix": "改为可验证的客观描述",
    }
    agent = ComplianceCheckerAgent(_MockChatModel(_llm_report_json([llm_finding])))

    report = await agent.a_check(
        script_text=script,
        region=ComplianceRegion.cn_mainland,
        product_category=ProductCategory.other,
    )

    rule_ids = {finding.rule_id for finding in report.findings}
    assert "cn_yanyi_label" in rule_ids
    assert "llm_semantic_overclaim" in rule_ids
    assert len(report.findings) == 2


@pytest.mark.asyncio
async def test_a_check_dedupes_overlapping_findings() -> None:
    """同 (rule_id, location) 同时来自两端 → 合并后只保留 1 条。"""

    # 用单规则引擎构造一条 banned_phrase 命中：
    rule_finding_dto = ComplianceFindingDTO(
        rule_id="dup_rule",
        rule_kind="banned_phrase",
        severity=ComplianceSeverity.warning,
        description="rule-side",
        location="char_offset:0",
        suggested_fix="rule fix",
        matched_text="bad",
    )
    llm_finding = ComplianceFinding(
        rule_id="dup_rule",
        rule_kind="banned_phrase",
        severity="warning",
        description="llm-side",
        location="char_offset:0",
        suggested_fix="llm fix",
    )

    merged = ComplianceCheckerAgent.merge_findings([rule_finding_dto], [llm_finding])

    assert len(merged) == 1
    # 规则端先入，未被严重等级覆盖时保留规则端文案。
    assert merged[0].description == "rule-side"


@pytest.mark.asyncio
async def test_a_check_keeps_higher_severity_on_dedupe() -> None:
    """同 (rule_id, location)：规则=warning，LLM=blocker → blocker 胜。"""

    rule_finding_dto = ComplianceFindingDTO(
        rule_id="esc_rule",
        rule_kind="banned_phrase",
        severity=ComplianceSeverity.warning,
        description="rule-side warning",
        location="char_offset:5",
        suggested_fix="rule fix",
        matched_text="bad",
    )
    llm_finding = ComplianceFinding(
        rule_id="esc_rule",
        rule_kind="banned_phrase",
        severity="blocker",
        description="llm-side blocker",
        location="char_offset:5",
        suggested_fix="llm fix",
    )

    merged = ComplianceCheckerAgent.merge_findings([rule_finding_dto], [llm_finding])

    assert len(merged) == 1
    assert merged[0].severity == "blocker"
    assert merged[0].description == "llm-side blocker"


# ---------------------------------------------------------------------------
# 2. 评分公式
# ---------------------------------------------------------------------------


def _make_finding(severity: str, suffix: str = "") -> ComplianceFinding:
    """构造任意严重等级的 ComplianceFinding 工厂（仅用于 score 测试）。"""

    return ComplianceFinding(
        rule_id=f"r_{severity}{suffix}",
        rule_kind="banned_phrase",
        severity=severity,  # type: ignore[arg-type]
        description="...",
        location=f"loc{suffix}",
        suggested_fix="...",
    )


def test_calculate_score_pure_blocker() -> None:
    """1 个 blocker → 100 - 25 = 75。"""

    findings = [_make_finding("blocker")]
    assert ComplianceCheckerAgent.calculate_score(findings) == 75


def test_calculate_score_pure_warning() -> None:
    """5 个 warning → 100 - 5*5 = 75。"""

    findings = [_make_finding("warning", suffix=str(i)) for i in range(5)]
    assert ComplianceCheckerAgent.calculate_score(findings) == 75


def test_calculate_score_mixed() -> None:
    """2 blockers + 3 warnings + 5 infos → 100 - 50 - 15 - 5 = 30。"""

    findings: list[ComplianceFinding] = []
    findings += [_make_finding("blocker", suffix=f"b{i}") for i in range(2)]
    findings += [_make_finding("warning", suffix=f"w{i}") for i in range(3)]
    findings += [_make_finding("info", suffix=f"i{i}") for i in range(5)]
    assert ComplianceCheckerAgent.calculate_score(findings) == 30


def test_calculate_score_floor_at_zero() -> None:
    """5 blockers → 100 - 125 = -25 → clamp 到 0。"""

    findings = [_make_finding("blocker", suffix=str(i)) for i in range(5)]
    assert ComplianceCheckerAgent.calculate_score(findings) == 0


# ---------------------------------------------------------------------------
# 3. 真实规则引擎集成
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_category_triggers_disclaimer_rule() -> None:
    """脚本不含免责声明 + product_category=health → 规则引擎产出 blocker。"""

    # 包含 "演绎" 让 yanyi 规则通过；但不含"非医疗器械"等健康免责短语。
    script = "演绎短片：分享我家的护肤品。"
    agent = ComplianceCheckerAgent(_MockChatModel(_empty_llm_report_json("cn_mainland", "health")))

    report = await agent.a_check(
        script_text=script,
        region=ComplianceRegion.cn_mainland,
        product_category=ProductCategory.health,
    )

    rule_ids = {finding.rule_id for finding in report.findings}
    assert "cn_health_disclaimer" in rule_ids
    disclaimer = next(f for f in report.findings if f.rule_id == "cn_health_disclaimer")
    assert disclaimer.severity == "blocker"
    assert disclaimer.rule_kind == "required_disclaimer"


@pytest.mark.asyncio
async def test_yanyi_label_missing_blocker() -> None:
    """脚本既无 演绎 也无 虚构 → cn_yanyi_label blocker。"""

    script = "今天给大家推荐一款产品。"  # 不含 演绎 / 虚构
    agent = ComplianceCheckerAgent(_MockChatModel(_empty_llm_report_json()))

    report = await agent.a_check(
        script_text=script,
        region=ComplianceRegion.cn_mainland,
        product_category=ProductCategory.other,
    )

    yanyi = next((f for f in report.findings if f.rule_id == "cn_yanyi_label"), None)
    assert yanyi is not None
    assert yanyi.severity == "blocker"
    assert yanyi.rule_kind == "required_label"


@pytest.mark.asyncio
async def test_brand_aliases_passed_through_to_rule_engine() -> None:
    """a_check 把 brand_aliases 透传到 rule_engine.scan(brand_aliases_override=...)。"""

    fake_engine = MagicMock(spec=ComplianceRuleEngine)
    fake_engine.scan.return_value = []
    agent = ComplianceCheckerAgent(
        _MockChatModel(_empty_llm_report_json()),
        rule_engine=fake_engine,
    )

    aliases = ("Acme", "ACME家")
    await agent.a_check(
        script_text="演绎短片",
        region=ComplianceRegion.cn_mainland,
        product_category=ProductCategory.electronics,
        script_duration_sec=90,
        brand_aliases=aliases,
    )

    fake_engine.scan.assert_called_once()
    _, kwargs = fake_engine.scan.call_args
    assert kwargs["brand_aliases_override"] == aliases
    assert kwargs["region"] is ComplianceRegion.cn_mainland
    assert kwargs["product_category"] is ProductCategory.electronics
    assert kwargs["script_duration_sec"] == 90


# ---------------------------------------------------------------------------
# 4. format_output / 配置 / 摘要
# ---------------------------------------------------------------------------


def test_format_output_handles_malformed_json_via_json_repair() -> None:
    """带末尾逗号 + 单引号 + 未引号键的 JSON 由 json_repair 修复后仍能解析。"""

    malformed = (
        "{variant_id: null, region: 'cn_mainland', product_category: 'other', "
        "findings: [], score: 100, summary: '未发现合规风险。',}"
    )
    agent = ComplianceCheckerAgent(_MockChatModel(""))

    report = agent.format_output(malformed)

    assert isinstance(report, ComplianceReport)
    assert report.region == "cn_mainland"
    assert report.findings == []
    assert report.score == 100


def test_agent_uses_json_schema_method() -> None:
    """W4-T3 决策 D5：commerce agent 使用 ``json_schema`` 结构化输出方式。"""

    agent = ComplianceCheckerAgent(_MockChatModel(_empty_llm_report_json()))

    assert agent._structured_output_method == "json_schema"
    # 装载默认 cn_mainland 规则集（防止有人改默认值）。
    assert agent._rule_engine.rules == CN_MAINLAND_RULES


def test_summary_text_for_clean_script() -> None:
    """空 findings → 中文摘要为"未发现合规风险。"。"""

    summary = ComplianceCheckerAgent._build_summary([])
    assert summary == "未发现合规风险。"


def test_summary_text_for_mixed_findings() -> None:
    """2 阻断 / 1 警告 / 1 提示 → 中文摘要包含三段计数。"""

    findings = [
        _make_finding("blocker", suffix="b1"),
        _make_finding("blocker", suffix="b2"),
        _make_finding("warning", suffix="w1"),
        _make_finding("info", suffix="i1"),
    ]
    summary = ComplianceCheckerAgent._build_summary(findings)
    assert "2 个阻断项" in summary
    assert "1 个警告" in summary
    assert "1 个提示" in summary
