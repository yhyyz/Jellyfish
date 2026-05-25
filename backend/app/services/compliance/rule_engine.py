"""合规规则引擎：基于 pyahocorasick 自动机的多模式精确匹配。

为什么存在：
    剧情带货脚本在发布前需要做关键词扫描（"卖惨"黑名单 / 必备"演绎"标识 /
    健康类免责声明 / 品牌口播频次上限等）。如果用 ``re.search`` 逐条规则
    扫一遍 500 字脚本，规则数 N=20+ 时复杂度是 ``O(N*L)`` 且每次都要重
    新编译；用 :mod:`pyahocorasick` 把所有禁词压成一个 Aho-Corasick 自动机
    后，单次 ``iter()`` 即可线性扫完文本，工程上 10–100× 快于 regex。

做什么：
    1. 暴露不可变的 :class:`RuleSpec` —— 定义单条规则（4 种 ``kind``）；
    2. 暴露 :class:`ComplianceRuleEngine` —— 在 ``__init__`` 一次性构建
       自动机，``scan(...)`` 时只做匹配 + 命中聚合，**绝不重建**；
    3. 暴露 :class:`ComplianceFindingDTO` —— 引擎产出的内存结构，与
       :class:`app.models.compliance.ComplianceFinding` ORM 解耦。

边界：
    - 本模块不依赖 ORM、不依赖 FastAPI、不依赖任何 W6 路由层；
    - 测试可以纯内存构造 ``ComplianceRuleEngine`` 反复调用 ``scan()``；
    - 规则集合（哪些规则属于哪个地区/品类）由调用方提供，本模块只是
      "把一堆 :class:`RuleSpec` 跑起来"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal

import ahocorasick

from app.models.types import (
    ComplianceRegion,
    ComplianceSeverity,
    ProductCategory,
)

# ---------------------------------------------------------------------------
# 类型别名
# ---------------------------------------------------------------------------

# 4 种规则类型；放在模块级 Literal，便于 ``RuleSpec.kind`` 静态校验。
RuleKind = Literal[
    "banned_phrase",
    "required_label",
    "required_disclaimer",
    "brand_mention_cap",
]


# ---------------------------------------------------------------------------
# 规则定义 / 输出 DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleSpec:
    """单条合规规则定义（不可变）。

    字段语义：
        id: 规则唯一 ID，用于 finding 回查与前端展示锚点。
        kind: 规则类型，决定走哪个匹配通路：
            - ``banned_phrase``     -> ``patterns`` 中任一命中即报问题；
            - ``required_label``    -> ``required_text`` 中任一出现即"满足"，
              否则报问题（用 ``|`` 分隔多个候选词，比如 ``"演绎|虚构"``）；
            - ``required_disclaimer`` -> 与 ``required_label`` 相同的"必须出现"
              语义，但只有 ``product_category`` 命中 ``product_category_filter``
              才触发；
            - ``brand_mention_cap`` -> 统计 ``brand_aliases`` 在文本中的出现
              次数，超过 ``cap_per_60s * (script_duration_sec / 60)`` 即报问题。
        severity: 严重等级（info/warning/blocker），决定是否阻塞发布。
        description: 中文规则说明（直接写入 finding）。
        suggested_fix: 中文修复建议（直接写入 finding）。
        patterns: 仅 ``banned_phrase`` 使用；多模式列表，引擎构建一个
            自动机统一扫描。
        required_text: 仅 ``required_label`` / ``required_disclaimer`` 使用；
            "需要出现"的文本；支持 ``|`` 拆分多候选词，命中其一即视为合规。
        cap_per_60s: 仅 ``brand_mention_cap`` 使用；每 60s 允许的最大次数；
            与脚本时长成线性比例。
        brand_aliases: 仅 ``brand_mention_cap`` 使用；同一品牌的所有别名。
        product_category_filter: 仅 ``required_disclaimer`` 使用；只有当
            ``ProductCategory`` 命中 filter 才触发该规则。
    """

    id: str
    kind: RuleKind
    severity: ComplianceSeverity
    description: str
    suggested_fix: str

    # banned_phrase 用 patterns
    patterns: tuple[str, ...] = ()

    # required_label / required_disclaimer 用 required_text
    # 支持 "演绎|虚构" 这种 OR 语义（不是 regex，纯字符串拆分）
    required_text: str | None = None

    # brand_mention_cap 用 cap_per_60s + brand_aliases
    cap_per_60s: int | None = None
    brand_aliases: tuple[str, ...] = ()

    # required_disclaimer 用：仅当 ProductCategory 命中 filter 才触发
    product_category_filter: tuple[ProductCategory, ...] = ()


@dataclass
class ComplianceFindingDTO:
    """规则引擎产出的内存 finding。

    与 :class:`app.models.compliance.ComplianceFinding` ORM 解耦；
    服务层在拿到一组 DTO 之后再决定：
        - 直接返回前端做"实时检查"展示；
        - 或写入 ``compliance_findings`` 表与某个 ``StoryVariant`` 关联。

    字段含义：
        rule_id / rule_kind / severity / description / suggested_fix:
            直接来自触发的 :class:`RuleSpec`，便于前端展示与回查规则。
        location: 命中位置；对 ``banned_phrase`` 是 ``"char_offset:N"``，
            对 ``required_label`` / ``required_disclaimer`` 是 ``None``，
            对 ``brand_mention_cap`` 是 ``"mention_count:K"``。
        matched_text: 命中的具体片段（``banned_phrase`` 用），便于 UI 高亮；
            其它规则保留 ``None`` 即可。
    """

    rule_id: str
    rule_kind: str
    severity: ComplianceSeverity
    description: str
    location: str | None = None
    suggested_fix: str | None = None
    matched_text: str | None = None


# ---------------------------------------------------------------------------
# 自动机条目元数据
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _AutomatonEntry:
    """挂在自动机叶子节点上的元数据：用于命中后构造 finding。"""

    rule_id: str
    severity: ComplianceSeverity
    description: str
    suggested_fix: str
    original_pattern: str  # 用户原始大小写，便于 matched_text 展示


# ---------------------------------------------------------------------------
# 引擎
# ---------------------------------------------------------------------------


@dataclass
class ComplianceRuleEngine:
    """合规规则引擎 —— 用 pyahocorasick 自动机做精确多模式匹配。

    使用约定：
        engine = ComplianceRuleEngine(rules=CN_MAINLAND_RULES)
        findings = engine.scan(
            script_text,
            region=ComplianceRegion.cn_mainland,
            product_category=ProductCategory.health,
            script_duration_sec=60,
            brand_aliases_override=("Acme",),  # 可选，仅 brand_mention_cap 用
        )

    设计要点：
        1. 自动机只在 ``__init__`` 构建一次。``make_automaton()`` 是 O(N) 但
           依然不便宜，绝不能放进 scan 路径。
        2. 文本匹配统一在 ``script_text.lower()`` 上做，规则模式入库前也
           做了 ``.lower()`` 归一化；中文不区分大小写但 ASCII 的 ``"Linda"``
           会落到 ``"linda"``。
        3. ``required_label`` / ``required_disclaimer`` 走 Python 内置子串
           检查，不进自动机：单条规则一次 ``in`` 比构建分支自动机更便宜。
        4. ``brand_mention_cap`` 走简单的 ``str.count`` 统计；P1 不需要支
           持模糊匹配。
    """

    _rules: tuple[RuleSpec, ...] = field(init=False)
    _banned_automaton: ahocorasick.Automaton = field(init=False, repr=False)
    _required_label_rules: tuple[RuleSpec, ...] = field(init=False, repr=False)
    _required_disclaimer_rules: tuple[RuleSpec, ...] = field(init=False, repr=False)
    _brand_cap_rules: tuple[RuleSpec, ...] = field(init=False, repr=False)

    def __init__(self, rules: Iterable[RuleSpec]) -> None:
        # 把 Iterable 实体化为 tuple，避免被外部消费成空生成器。
        materialized = tuple(rules)
        # 在 frozen=False 的 dataclass 上仍然走 __setattr__ 即可。
        object.__setattr__(self, "_rules", materialized)
        object.__setattr__(
            self,
            "_banned_automaton",
            self._build_automaton(
                tuple(r for r in materialized if r.kind == "banned_phrase")
            ),
        )
        object.__setattr__(
            self,
            "_required_label_rules",
            tuple(r for r in materialized if r.kind == "required_label"),
        )
        object.__setattr__(
            self,
            "_required_disclaimer_rules",
            tuple(r for r in materialized if r.kind == "required_disclaimer"),
        )
        object.__setattr__(
            self,
            "_brand_cap_rules",
            tuple(r for r in materialized if r.kind == "brand_mention_cap"),
        )

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    @property
    def rules(self) -> tuple[RuleSpec, ...]:
        """对外暴露当前装载的全量规则（只读）。"""

        return self._rules

    def scan(
        self,
        script_text: str,
        *,
        region: ComplianceRegion,  # pylint: disable=unused-argument
        product_category: ProductCategory,
        script_duration_sec: int = 60,
        brand_aliases_override: tuple[str, ...] | None = None,
    ) -> list[ComplianceFindingDTO]:
        """扫描脚本文本，按 4 类规则收集 finding 并返回。

        Args:
            script_text: 待检查的脚本/字幕原文。
            region: 调用方声明的合规地区；当前 P1 仅用于日志/调用方过滤，
                引擎本身不再二次过滤（规则集已经按地区分组传入）。
            product_category: 商品品类；驱动 ``required_disclaimer`` 是否
                启用（当且仅当 ``filter`` 命中时启用）。
            script_duration_sec: 脚本时长（秒），驱动 brand cap 阈值线性
                外推（cap = ``cap_per_60s * (duration / 60)``）。
            brand_aliases_override: 临时覆盖规则里的 ``brand_aliases``；
                P1 中 ``cn_brand_mention_cap_60s`` 默认 ``brand_aliases=()``，
                运行期由调用方注入项目品牌词表（P2 会迁移到 Project 字段）。

        Returns:
            一个 :class:`ComplianceFindingDTO` 列表；空列表代表完全合规。
        """

        # 1. banned_phrase：统一在 lowercase 文本上扫自动机。
        normalized = script_text.lower()
        findings: list[ComplianceFindingDTO] = []
        findings.extend(self._scan_banned(normalized))

        # 2. required_label：必须包含某段文本（支持 "A|B" OR 语义）。
        findings.extend(self._scan_required(self._required_label_rules, normalized))

        # 3. required_disclaimer：与 required_label 同语义，但仅当 product_category
        #    命中 filter 时启用（避免对非健康类商品误触发）。
        for rule in self._required_disclaimer_rules:
            if rule.product_category_filter and product_category not in rule.product_category_filter:
                continue
            findings.extend(self._scan_required((rule,), normalized))

        # 4. brand_mention_cap：按时长线性外推阈值，统计命中次数。
        findings.extend(
            self._scan_brand_cap(
                normalized,
                script_duration_sec=script_duration_sec,
                aliases_override=brand_aliases_override,
            )
        )

        return findings

    # ------------------------------------------------------------------
    # 自动机构建
    # ------------------------------------------------------------------

    @staticmethod
    def _build_automaton(rules: tuple[RuleSpec, ...]) -> ahocorasick.Automaton:
        """从 ``banned_phrase`` 规则集合构建一个 Aho-Corasick 自动机。

        每个 ``pattern`` 都被 ``.lower()`` 归一化后加入自动机，叶子节点
        挂 :class:`_AutomatonEntry`，命中时直接还原成 finding。

        即便没有任何 ``banned_phrase`` 规则也会构建一个空自动机，让
        ``scan()`` 路径无需做 None 判断（``iter()`` 在空自动机上即时返回）。
        """

        automaton = ahocorasick.Automaton()
        for rule in rules:
            for pattern in rule.patterns:
                if not pattern:
                    continue  # 防御性：丢弃空字符串，避免 iter 死循环。
                normalized = pattern.lower()
                entry = _AutomatonEntry(
                    rule_id=rule.id,
                    severity=rule.severity,
                    description=rule.description,
                    suggested_fix=rule.suggested_fix,
                    original_pattern=pattern,
                )
                automaton.add_word(normalized, entry)
        # 即使没有任何 word，仍然显式 make_automaton；iter() 会在空自动机
        # 上立即返回空生成器，简化 scan() 控制流。
        try:
            automaton.make_automaton()
        except (ValueError, AttributeError):
            # pyahocorasick 在没有 word 时偶尔会拒绝 make；忽略后用空机。
            pass
        return automaton

    # ------------------------------------------------------------------
    # 各类规则的匹配实现
    # ------------------------------------------------------------------

    def _scan_banned(self, normalized_text: str) -> list[ComplianceFindingDTO]:
        """对 ``banned_phrase`` 规则做一次自动机扫描。

        ``ahocorasick.Automaton.iter`` 会返回 ``(end_index, value)`` 序列，
        end_index 是匹配子串的最后一个字符在 normalized_text 中的下标。
        我们用 ``end_index - len(pattern) + 1`` 还原起点，构造 location。

        多个不同规则覆盖同一字符串时，自动机会分别命中（不会互相吞掉），
        引擎也不做"压缩"——上层 UI/Service 自己决定是否聚合。
        """

        findings: list[ComplianceFindingDTO] = []
        for end_idx, entry in self._banned_automaton.iter(normalized_text):
            start = end_idx - len(entry.original_pattern) + 1
            findings.append(
                ComplianceFindingDTO(
                    rule_id=entry.rule_id,
                    rule_kind="banned_phrase",
                    severity=entry.severity,
                    description=entry.description,
                    location=f"char_offset:{start}",
                    suggested_fix=entry.suggested_fix,
                    matched_text=entry.original_pattern,
                )
            )
        return findings

    @staticmethod
    def _scan_required(
        rules: tuple[RuleSpec, ...],
        normalized_text: str,
    ) -> list[ComplianceFindingDTO]:
        """对 ``required_label`` / ``required_disclaimer`` 规则做必现检查。

        ``required_text`` 用 ``|`` 拆分成多个候选词；只要文本中包含其中
        任何一个，就视为"满足"。否则产出一条 finding。
        """

        findings: list[ComplianceFindingDTO] = []
        for rule in rules:
            if not rule.required_text:
                continue  # 没配置就跳过，防御坏数据。
            candidates = [c.lower() for c in rule.required_text.split("|") if c]
            if not candidates:
                continue
            satisfied = any(c in normalized_text for c in candidates)
            if not satisfied:
                findings.append(
                    ComplianceFindingDTO(
                        rule_id=rule.id,
                        rule_kind=rule.kind,
                        severity=rule.severity,
                        description=rule.description,
                        location=None,
                        suggested_fix=rule.suggested_fix,
                        matched_text=None,
                    )
                )
        return findings

    def _scan_brand_cap(
        self,
        normalized_text: str,
        *,
        script_duration_sec: int,
        aliases_override: tuple[str, ...] | None,
    ) -> list[ComplianceFindingDTO]:
        """对 ``brand_mention_cap`` 规则做次数检查。

        次数统计 = sum(text.count(alias) for alias in aliases)，所有别名
        都贡献一次"出现"。重叠场景（"Acme家"包含"Acme"）会按子串各计一次，
        P1 不做去重，简单且与运营预期一致。
        """

        if script_duration_sec <= 0:
            return []
        findings: list[ComplianceFindingDTO] = []
        for rule in self._brand_cap_rules:
            cap = rule.cap_per_60s
            if cap is None:
                continue
            aliases = aliases_override if aliases_override is not None else rule.brand_aliases
            if not aliases:
                # P1: 静态规则的 brand_aliases 默认为空；调用方未注入时
                # 直接跳过该规则，避免误判。
                continue
            total = 0
            for alias in aliases:
                if not alias:
                    continue
                total += normalized_text.count(alias.lower())
            threshold = cap * (script_duration_sec / 60.0)
            if total > threshold:
                findings.append(
                    ComplianceFindingDTO(
                        rule_id=rule.id,
                        rule_kind="brand_mention_cap",
                        severity=rule.severity,
                        description=rule.description,
                        location=f"mention_count:{total}",
                        suggested_fix=rule.suggested_fix,
                        matched_text=None,
                    )
                )
        return findings


__all__ = [
    "ComplianceFindingDTO",
    "ComplianceRuleEngine",
    "RuleKind",
    "RuleSpec",
]
