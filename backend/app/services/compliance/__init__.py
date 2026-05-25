"""剧情带货合规检查（Story-Driven Commerce Compliance）业务服务包。

P1 阶段聚焦：
- :mod:`rule_engine`：基于 ``pyahocorasick`` 自动机的多模式精确匹配引擎，
  统一处理 ``banned_phrase`` / ``required_label`` / ``required_disclaimer`` /
  ``brand_mention_cap`` 四类规则，按 ``ComplianceSeverity`` 输出 finding。
- :mod:`builtin_rules`：``cn_mainland_default`` 内置规则集（8 条 P1 规则
  + 1 个系统级 ``ComplianceProfile`` 定义）。
- :mod:`bootstrap_compliance`：启动时调用的幂等 bootstrap，把内置 profile
  写入 ``compliance_profiles`` 表。

不在 P1 范围内（故意排除）：
- ``cn_mainland_health`` / ``overseas_default`` / ``hk_tw`` 等额外 profile（P2）；
- 合规相关 API/Service 编排（W6）。

层职责约定：
- 本包只做"规则定义 + 内存匹配 + 系统级 seed"，不直接处理 HTTP 路由或
  跨层 DTO；ORM 仅在 :mod:`bootstrap_compliance` 中读写。
- 保持与 :mod:`app.services.commerce`、:mod:`app.services.studio` 同级，
  方便 W6 Compliance API 复用。
"""

from app.services.compliance.rule_engine import (
    ComplianceFindingDTO,
    ComplianceRuleEngine,
    RuleKind,
    RuleSpec,
)

__all__ = [
    "ComplianceFindingDTO",
    "ComplianceRuleEngine",
    "RuleKind",
    "RuleSpec",
]
