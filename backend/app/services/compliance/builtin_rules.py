"""``cn_mainland_default`` 内置合规规则集（W3-T3, P1）。

为什么存在：
    剧情带货脚本在中国大陆主流平台（抖音/快手/小红书）发布前，必须满足
    一组最小可用的合规约束（演绎标识、卖惨黑名单、伪造身份、群体丑化、
    品牌口播频次、健康类免责、不可验证宣称、虚假政策）。这 8 条规则是
    W3-T3 P1 的"内置"清单，由 :func:`bootstrap_builtin_compliance_profiles`
    幂等写入 ``compliance_profiles`` 表，并由
    :class:`app.services.compliance.rule_engine.ComplianceRuleEngine` 在线消费。

做什么：
    1. 定义 :data:`CN_MAINLAND_RULES`：8 条 :class:`RuleSpec` 元组，按地域+
       品类（必要时）切换；
    2. 定义 :data:`CN_MAINLAND_DEFAULT_PROFILE`：系统级 :class:`ComplianceProfileDefinition`
       封装，供 bootstrap 直接序列化入库；
    3. 暴露 :func:`serialize_rule` —— 把 :class:`RuleSpec` 转成 JSON 友好的
       dict，存入 ``compliance_profiles.rules`` 列。

边界：
    - 这里只放 ``cn_mainland_default``。``cn_mainland_health`` /
      ``overseas_default`` / ``hk_tw`` 等留给 P2，禁止在 P1 引入；
    - 规则的"严重等级"参考立法风险与平台审核惯例选择，调整请走 plan。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.types import (
    ComplianceRegion,
    ComplianceSeverity,
    ProductCategory,
)
from app.services.compliance.rule_engine import RuleSpec

# ---------------------------------------------------------------------------
# 单条规则定义 —— 8 条 cn_mainland_default 规则
# ---------------------------------------------------------------------------

# Rule 1：演绎/虚构标识（剧情类内容必备的"非真实事件"标签）。
_RULE_YANYI_LABEL = RuleSpec(
    id="cn_yanyi_label",
    kind="required_label",
    severity=ComplianceSeverity.blocker,
    description="中国大陆短视频广告必须包含'演绎'或'虚构'标识",
    suggested_fix="在视频开头或结尾添加'演绎'或'剧情虚构'文字标签",
    # 用 "|" 拆分多候选词，命中其一即视为合规。
    required_text="演绎|虚构",
)

# Rule 2：卖惨黑名单（典型"哭穷套路"，平台明令禁止）。
_RULE_BANNED_MAICAI = RuleSpec(
    id="cn_banned_maicai",
    kind="banned_phrase",
    severity=ComplianceSeverity.blocker,
    description="禁止使用'卖惨/哭穷'类博取同情的话术",
    suggested_fix="改为正向叙事，去除'卖惨''哭穷''跪求'等话术",
    patterns=(
        "卖惨",
        "哭穷",
        "跪求",
        "我太惨了",
        "求求大家",
        "实在太可怜",
    ),
)

# Rule 3：伪造身份/学历（典型"悉尼大学Linda教授"骗局，平台高风险）。
_RULE_BANNED_FAKE_CREDENTIALS = RuleSpec(
    id="cn_banned_fake_credentials",
    kind="banned_phrase",
    severity=ComplianceSeverity.warning,
    description="疑似伪造身份/学历表述（如海外名校教授、博士头衔）",
    suggested_fix="移除未经核实的学历/身份描述，或附上可验证资质",
    patterns=(
        "悉尼大学",
        "Linda教授",
        "linda教授",
        "哈佛博士",
        "剑桥博士",
        "牛津教授",
        "麻省理工博士",
        "斯坦福教授",
        "海归博士",
        "前央视记者",
    ),
)

# Rule 4：群体丑化（贬损特定群体，违反"网络信息内容生态治理规定"）。
_RULE_BANNED_GROUP_DENIGRATION = RuleSpec(
    id="cn_banned_group_denigration",
    kind="banned_phrase",
    severity=ComplianceSeverity.warning,
    description="疑似贬损/丑化特定群体",
    suggested_fix="改为针对行为或观点的中性表达，避免群体标签",
    patterns=(
        "农村人",
        "穷人就是",
        "没钱的人",
        "这种人",
        "你们这种",
        "老实人活该",
        "底层人",
        "屌丝",
    ),
)

# Rule 5：60s 内品牌口播频次（避免硬广感过强；P1 brand_aliases 由调用方注入）。
_RULE_BRAND_MENTION_CAP_60S = RuleSpec(
    id="cn_brand_mention_cap_60s",
    kind="brand_mention_cap",
    severity=ComplianceSeverity.warning,
    description="60 秒内品牌口播次数上限为 2 次",
    suggested_fix="将多次品牌名替换为'它/这款产品'等指代，或拆分到不同分镜",
    cap_per_60s=2,
    # P1: brand_aliases 默认为空；运行时由 scan(brand_aliases_override=...) 注入；
    # P2 计划把 brand_aliases 存到 Project 字段并自动注入。
    brand_aliases=(),
)

# Rule 6：健康类商品免责（"非医疗器械"是关键合规信号）。
_RULE_HEALTH_DISCLAIMER = RuleSpec(
    id="cn_health_disclaimer",
    kind="required_disclaimer",
    severity=ComplianceSeverity.blocker,
    description="健康类商品脚本必须包含医疗免责声明（如'非医疗器械'）",
    suggested_fix="在视频结尾追加'本视频为剧情演绎，产品功效因人而异，非医疗器械'",
    # 任一候选命中即合规：完整声明 OR 关键短语 "非医疗器械"。
    required_text="本视频为剧情演绎，产品功效因人而异，非医疗器械|非医疗器械",
    product_category_filter=(ProductCategory.health,),
)

# Rule 7：不可验证宣称（"仅限今日"等紧迫话术）。
_RULE_UNVERIFIABLE_URGENCY = RuleSpec(
    id="cn_unverifiable_urgency",
    kind="banned_phrase",
    severity=ComplianceSeverity.warning,
    description="疑似不可验证的紧迫性宣称（如'仅限今日'）",
    suggested_fix="提供可核实的有效期/库存来源，或改为日常促销表达",
    patterns=(
        "仅限今日",
        "仅限24小时",
        "错过等10年",
        "千载难逢",
        "最后一天",
        "只剩最后",
    ),
)

# Rule 8：虚假政策宣称（"国补下线倒计时"是高频违规话术）。
_RULE_FAKE_POLICY_CLAIM = RuleSpec(
    id="cn_fake_policy_claim",
    kind="banned_phrase",
    severity=ComplianceSeverity.blocker,
    description="疑似虚假政策/补贴宣称（涉及政府/国务院字样的不实表达）",
    suggested_fix="移除涉及政府/国务院的不实补贴话术，或改用平台官方促销名称",
    patterns=(
        "国补下线倒计时",
        "政府补贴最后一天",
        "限量国补",
        "国务院通知",
        "政府发钱",
        "国家发补贴",
    ),
)


CN_MAINLAND_RULES: tuple[RuleSpec, ...] = (
    _RULE_YANYI_LABEL,
    _RULE_BANNED_MAICAI,
    _RULE_BANNED_FAKE_CREDENTIALS,
    _RULE_BANNED_GROUP_DENIGRATION,
    _RULE_BRAND_MENTION_CAP_60S,
    _RULE_HEALTH_DISCLAIMER,
    _RULE_UNVERIFIABLE_URGENCY,
    _RULE_FAKE_POLICY_CLAIM,
)


# ---------------------------------------------------------------------------
# Profile 定义
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComplianceProfileDefinition:
    """系统级 :class:`ComplianceProfile` 的内存定义（不可变）。

    与 ORM 解耦；bootstrap 在写库前调用 :func:`serialize_rules` 把
    ``rules`` 序列化成 JSON 友好结构，存入 ``compliance_profiles.rules``。
    """

    id: str  # ComplianceProfile.id
    name: str
    region: ComplianceRegion
    description: str
    rules: tuple[RuleSpec, ...]


CN_MAINLAND_DEFAULT_PROFILE = ComplianceProfileDefinition(
    id="cn_mainland_default",
    name="中国大陆默认合规规则集",
    region=ComplianceRegion.cn_mainland,
    description=(
        "P1 内置：演绎标识、卖惨黑名单、伪造身份、群体丑化、品牌口播频次、"
        "健康类免责、不可验证宣称、虚假政策"
    ),
    rules=CN_MAINLAND_RULES,
)


# ---------------------------------------------------------------------------
# 序列化辅助
# ---------------------------------------------------------------------------


def serialize_rule(rule: RuleSpec) -> dict[str, Any]:
    """把单条 :class:`RuleSpec` 序列化为 JSON 友好的 dict。

    序列化策略：
        - 枚举展平为 ``.value`` 字符串；
        - tuple 字段展平为 list；
        - ``None`` 直接保留，便于回读时还原 ``RuleSpec``。
    """

    return {
        "id": rule.id,
        "kind": rule.kind,
        "severity": rule.severity.value,
        "description": rule.description,
        "suggested_fix": rule.suggested_fix,
        "patterns": list(rule.patterns),
        "required_text": rule.required_text,
        "cap_per_60s": rule.cap_per_60s,
        "brand_aliases": list(rule.brand_aliases),
        "product_category_filter": [
            cat.value for cat in rule.product_category_filter
        ],
    }


def serialize_rules(rules: tuple[RuleSpec, ...]) -> list[dict[str, Any]]:
    """批量序列化规则集合（顺序保持原 tuple 顺序）。"""

    return [serialize_rule(rule) for rule in rules]


__all__ = [
    "CN_MAINLAND_DEFAULT_PROFILE",
    "CN_MAINLAND_RULES",
    "ComplianceProfileDefinition",
    "serialize_rule",
    "serialize_rules",
]
