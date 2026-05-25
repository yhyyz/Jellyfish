"""``ComplianceProfile`` / ``ComplianceFinding`` 的只读 read schema（W6-T3）。

设计要点
--------

本模块只承载“读视图”——前端 studio/compliance 面板会渲染规则集列表、
规则集详情、变体级 finding 列表三类视图。``ComplianceProfile.rules``
直接以 ``list[dict[str, Any]]`` 回传规则数组的原始 JSON，避免在 read
schema 上重新声明一份和 :class:`app.services.compliance.rule_engine.RuleSpec`
重叠但又不完全等价的 Pydantic 类（那会让规则 schema 维护成本翻倍）。

为什么不给 ``rules`` 收口一个具体的 Pydantic 类型：
    规则结构在 P1/P2 间会演化（``required_label`` / ``required_disclaimer``
    / ``brand_mention_cap`` 各自有不同字段），强行收口意味着每加一条
    新规则类型都要改 read schema，与“前端只是渲染原始 JSON”的需求不
    匹配。这里以 ``list[dict]`` 透传，复杂校验留在 service / worker。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ComplianceProfileRead(BaseModel):
    """``ComplianceProfile`` 的只读视图。

    Attributes:
        id: profile ID（如 ``cn_mainland_default``），可在配置/代码中引用。
        name: 显示名称。
        region: 适用地域字符串（``cn_mainland`` / ``hk_tw`` / ``overseas``）。
        rules: 规则数组 JSON，结构由 :mod:`app.services.compliance.builtin_rules`
            决定；前端按 ``kind`` 字段分支渲染。
        is_system: 是否系统预置；预置 profile 不允许业务侧删除。
        description: 用途说明，前端展示在卡片副标题位置。
        created_at: 创建时间，便于审计。
    """

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="profile ID（如 cn_mainland_default）")
    name: str = Field(..., description="显示名称")
    region: str = Field(..., description="适用地域：cn_mainland / hk_tw / overseas")
    rules: list[dict[str, Any]] = Field(default_factory=list, description="规则数组 JSON")
    is_system: bool = Field(..., description="是否系统预置")
    description: str = Field(default="", description="profile 用途说明")
    created_at: datetime = Field(..., description="创建时间")


class ComplianceFindingRead(BaseModel):
    """``ComplianceFinding`` 的只读视图。

    Attributes:
        id: 自增主键。
        variant_id: 所属变体 ID（``story_variants.id`` 外键）。
        severity: 严重度字符串（``info`` / ``warning`` / ``blocker``）。
        rule_id: 触发的规则 ID。
        rule_kind: 规则类型（``banned_phrase`` / ``required_label`` / 等）。
        description: 问题描述。
        location: 命中位置（如 ``"Shot 3, dialog line 2"``），可能为空。
        suggested_fix: 建议修复方案，可能为空。
        is_resolved: 是否已解决；前端默认筛掉已解决项。
        detected_at: 检测时间。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="自增主键")
    variant_id: str = Field(..., description="所属变体 ID")
    severity: str = Field(..., description="严重度：info / warning / blocker")
    rule_id: str = Field(..., description="触发的规则 ID")
    rule_kind: str = Field(..., description="规则类型：banned_phrase / required_label / ...")
    description: str = Field(..., description="问题描述")
    location: str | None = Field(default=None, description="命中位置（如 'Shot 3, dialog line 2'）")
    suggested_fix: str | None = Field(default=None, description="建议修复方案")
    is_resolved: bool = Field(..., description="是否已解决")
    detected_at: datetime = Field(..., description="检测时间")


__all__ = [
    "ComplianceFindingRead",
    "ComplianceProfileRead",
]
