"""内置合规规则集（W3-T3 起草 P1，W11-T4 扩展 P2）。

为什么存在：
    剧情带货脚本在不同地区/品类发布前，必须满足一组最小可用的合规约束。
    本模块集中定义了系统预置（``is_system=True``）的合规规则与 profile，
    由 :func:`bootstrap_builtin_compliance_profiles` 幂等写入
    ``compliance_profiles`` 表，并由
    :class:`app.services.compliance.rule_engine.ComplianceRuleEngine` 在线消费。

做什么：
    1. :data:`CN_MAINLAND_RULES` —— 中国大陆默认 8 条规则；
    2. :data:`CN_MAINLAND_HEALTH_RULES` —— 在 ``CN_MAINLAND_RULES`` 之上叠加
       4 条健康类专项规则，仅供 :class:`ProductCategory.health` 项目使用；
    3. :data:`OVERSEAS_RULES` —— 海外默认 5 条核心规则（虚假资历、极致宣称、
       虚假紧迫、广告标识、品牌频次）；
    4. 三个 :class:`ComplianceProfileDefinition`：
       :data:`CN_MAINLAND_DEFAULT_PROFILE` /
       :data:`CN_MAINLAND_HEALTH_PROFILE` /
       :data:`OVERSEAS_DEFAULT_PROFILE`；
    5. :func:`serialize_rule` / :func:`serialize_rules`：把规则结构展平成
       JSON 友好的 dict / list，写入 ``compliance_profiles.rules`` 列。

边界：
    - 规则的"严重等级"参考立法风险与平台审核惯例选择，调整请走 plan；
    - ``hk_tw`` 暂未提供专属 profile，留给后续 plan；
    - ``cn_mainland_health`` 仅在调用方按 :class:`ProductCategory.health`
      项目挑选 profile 时生效；引擎本身不会对 banned_phrase 做品类过滤。
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
# cn_mainland_health 专项规则集（W11-T4）
# ---------------------------------------------------------------------------
# 在 cn_mainland_default 8 条规则基础上，叠加 4 条专门针对健康/保健类商品
# 的强约束。调用方需在项目品类为 ProductCategory.health 时选择此 profile，
# 引擎不会自动对 banned_phrase 做品类过滤（``product_category_filter`` 仅
# 对 required_disclaimer 生效）。

# 健康类 Rule A：禁止暗示治疗 / 治愈 / 疗效（高风险，立法层禁区）。
_RULE_HEALTH_NO_EFFICACY_CLAIM = RuleSpec(
    id="cn_health_no_efficacy_claim",
    kind="banned_phrase",
    severity=ComplianceSeverity.blocker,
    description="禁止暗示治疗/治愈/疗效",
    suggested_fix="改用'帮助舒缓'/'有助于'等弱化表述",
    patterns=(
        "治愈",
        "根除",
        "包治",
        "痊愈",
        "治疗",
        "克服",
        "彻底解决",
        "100%有效",
    ),
    product_category_filter=(ProductCategory.health,),
)

# 健康类 Rule B：必须包含完整免责声明（区别于 cn_health_disclaimer 的核心短语
# 兼容版本，此处要求出现"剧情演绎 + 功效因人而异"的完整句式）。
_RULE_HEALTH_REQUIRED_DISCLAIMER = RuleSpec(
    id="cn_health_required_disclaimer",
    kind="required_disclaimer",
    severity=ComplianceSeverity.blocker,
    description="健康类必须包含完整免责声明",
    suggested_fix="在视频结尾添加：本视频为剧情演绎，产品功效因人而异，非医疗器械",
    required_text="本视频为剧情演绎，产品功效因人而异",
    product_category_filter=(ProductCategory.health,),
)

# 健康类 Rule C：禁用医疗专业术语（避免被误认为医疗器械/处方品）。
_RULE_HEALTH_NO_MEDICAL_TERMS = RuleSpec(
    id="cn_health_no_medical_terms",
    kind="banned_phrase",
    severity=ComplianceSeverity.warning,
    description="健康类禁用医疗专业术语",
    suggested_fix="改用日常表达",
    patterns=(
        "处方",
        "诊断",
        "病症",
        "症状缓解",
        "副作用",
        "病情",
    ),
    product_category_filter=(ProductCategory.health,),
)

# 健康类 Rule D：禁用年龄群体绝对承诺（"80岁也能"/"60岁回到20岁"等违规话术）。
_RULE_HEALTH_NO_AGE_SPECIFIC_CLAIM = RuleSpec(
    id="cn_health_no_age_specific_claim",
    kind="banned_phrase",
    severity=ComplianceSeverity.warning,
    description="健康类禁用年龄群体绝对承诺",
    suggested_fix="改为'许多 X 岁人群反馈'",
    patterns=(
        "80岁也能",
        "60岁回到20岁",
        "再老也能",
    ),
    product_category_filter=(ProductCategory.health,),
)


CN_MAINLAND_HEALTH_RULES: tuple[RuleSpec, ...] = (
    *CN_MAINLAND_RULES,
    _RULE_HEALTH_NO_EFFICACY_CLAIM,
    _RULE_HEALTH_REQUIRED_DISCLAIMER,
    _RULE_HEALTH_NO_MEDICAL_TERMS,
    _RULE_HEALTH_NO_AGE_SPECIFIC_CLAIM,
)


CN_MAINLAND_HEALTH_PROFILE = ComplianceProfileDefinition(
    id="cn_mainland_health",
    name="中国大陆健康类专项合规",
    region=ComplianceRegion.cn_mainland,
    description=(
        "cn_mainland_default 基础上叠加健康类专项 4 条规则。仅对 "
        "ProductCategory.health 项目生效。"
    ),
    rules=CN_MAINLAND_HEALTH_RULES,
)


# ---------------------------------------------------------------------------
# overseas_default 海外默认规则集（W11-T4）
# ---------------------------------------------------------------------------
# 海外平台（YouTube / TikTok / Meta）相对宽松，但仍有 5 条不可逾越的红线：
# 虚假资历、极致宣称、虚假紧迫性、广告/演绎标识、品牌频次（cap=3 较国内宽松）。

# 海外 Rule A：禁止虚构学历或资历。
_RULE_OVERSEAS_NO_MADE_UP_CREDENTIALS = RuleSpec(
    id="overseas_no_made_up_credentials",
    kind="banned_phrase",
    severity=ComplianceSeverity.warning,
    description="禁止虚构学历或资历",
    suggested_fix="改为'用户'/'用户A/B/C'",
    patterns=(
        "Harvard PhD",
        "Oxford Professor",
        "MIT scientist",
        "Dr. Smith",
        "Yale researcher",
    ),
)

# 海外 Rule B：禁止不可验证的极致宣称（"guaranteed"/"miracle"等）。
_RULE_OVERSEAS_NO_UNVERIFIABLE_OUTCOME = RuleSpec(
    id="overseas_no_unverifiable_outcome",
    kind="banned_phrase",
    severity=ComplianceSeverity.warning,
    description="禁止不可验证的极致宣称",
    suggested_fix="改用'may help'/'has helped users'",
    patterns=(
        "guaranteed results",
        "100% effective",
        "lose 30 pounds in 7 days",
        "miracle cure",
    ),
)

# 海外 Rule C：禁止虚假紧迫性话术（FTC 重点关注）。
_RULE_OVERSEAS_NO_MISLEADING_URGENCY = RuleSpec(
    id="overseas_no_misleading_urgency",
    kind="banned_phrase",
    severity=ComplianceSeverity.warning,
    description="禁止虚假紧迫性",
    suggested_fix="使用'limited stock'/'while supplies last'",
    patterns=(
        "today only",
        "last 24 hours",
        "ending soon",
        "before midnight",
    ),
)

# 海外 Rule D：必须包含 dramatization / ad / sponsored 任一标签。
# 引擎扫描时对 ``required_text`` 候选词做 ``.lower()`` 归一化，原文中的
# "Dramatization" / "#ad" / "#sponsored" 均能命中。
_RULE_OVERSEAS_REQUIRED_AUTHENTIC_LABEL = RuleSpec(
    id="overseas_required_authentic_label",
    kind="required_label",
    severity=ComplianceSeverity.warning,
    description="包含演员演绎需注明",
    suggested_fix="添加 'Dramatization' 或 '#ad' / '#sponsored'",
    required_text="dramatization|ad|sponsored",
)

# 海外 Rule E：60s 脚本品牌名提及不超 3 次（cap=3 较国内 cap=2 宽松）。
_RULE_OVERSEAS_BRAND_MENTION_CAP_60S = RuleSpec(
    id="overseas_brand_mention_cap_60s",
    kind="brand_mention_cap",
    severity=ComplianceSeverity.warning,
    description="60s 脚本品牌名提及不超 3 次（海外较国内宽松）",
    suggested_fix="替换为代词或'this product'",
    cap_per_60s=3,
    brand_aliases=(),
)


OVERSEAS_RULES: tuple[RuleSpec, ...] = (
    _RULE_OVERSEAS_NO_MADE_UP_CREDENTIALS,
    _RULE_OVERSEAS_NO_UNVERIFIABLE_OUTCOME,
    _RULE_OVERSEAS_NO_MISLEADING_URGENCY,
    _RULE_OVERSEAS_REQUIRED_AUTHENTIC_LABEL,
    _RULE_OVERSEAS_BRAND_MENTION_CAP_60S,
)


OVERSEAS_DEFAULT_PROFILE = ComplianceProfileDefinition(
    id="overseas_default",
    name="海外默认合规",
    region=ComplianceRegion.overseas,
    description=(
        "海外市场默认规则集 — 5 条核心：虚假资历、极致宣称、虚假紧迫、"
        "广告标识、品牌频次（cap=3 比国内宽松）。"
    ),
    rules=OVERSEAS_RULES,
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
    "CN_MAINLAND_HEALTH_PROFILE",
    "CN_MAINLAND_HEALTH_RULES",
    "CN_MAINLAND_RULES",
    "ComplianceProfileDefinition",
    "OVERSEAS_DEFAULT_PROFILE",
    "OVERSEAS_RULES",
    "serialize_rule",
    "serialize_rules",
]
