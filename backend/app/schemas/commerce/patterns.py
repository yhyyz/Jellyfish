"""Pattern library 只读响应 schemas（W14-T4，P2 钩子/CTA/原型选择器）。

本模块聚合 P2 钩子工作流（Wave 13/14）下三类系统级"运营/产品资产"的
只读 DTO，对应 :class:`app.models.hook_pattern.HookPattern` /
:class:`app.models.cta_pattern.CtaPattern` /
:class:`app.models.brand_archetype.BrandArchetype` 三张注册表：

- :class:`HookPatternRead` —— 10 条钩子模式的列表/详情视图。
- :class:`CtaPatternRead` —— 5 条 CTA 模式的列表/详情视图。
- :class:`BrandArchetypeRead` —— 12 条品牌人格原型的列表/详情视图。

只读语义：
- 三张表均为系统级种子（``is_system=True``），由
  :func:`app.services.commerce.builtin_hook_patterns.bootstrap_builtin_hook_patterns`
  / :func:`app.services.commerce.builtin_cta_patterns.bootstrap_builtin_cta_patterns`
  / :func:`app.services.commerce.builtin_brand_archetypes.bootstrap_builtin_brand_archetypes`
  在启动期幂等加载，应用层接口不允许新增/编辑/删除；
- 因此本模块只暴露读取所需 DTO，不提供 Create/Update。

字段语义：
- 所有响应字段与 ORM 列严格对齐；
- JSON 列（``use_cases`` / ``avoid_cases`` / ``sample_phrases`` /
  ``voice_traits`` / ``speech_patterns`` / ``sample_brands``）保留原始
  结构，不在 schema 层做二次解析；
- ``created_at`` 来自 :class:`app.models.base.TimestampMixin`，方便前端
  在选择器列表里用于辅助排序或 debug。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HookPatternRead(BaseModel):
    """HookPattern 只读响应。

    用于 ``GET /api/v1/studio/hook-patterns`` 列表与详情。字段直接映射自
    ORM 列，便于前端钩子选择器直接消费。
    """

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="钩子 ID（如 question_hook）")
    name: str = Field(..., description="中文名称（如 问句钩子）")
    pattern_type: str = Field(
        ...,
        description="钩子类型：question / conflict / contrast / ...",
    )
    description: str = Field(..., description="钩子说明（运营/UI 展示）")
    template_text: str = Field(..., description="Jinja2 模板片段")
    psychology: str = Field(..., description="心理学原理")
    use_cases: list[str] = Field(
        default_factory=list,
        description="适用场景列表",
    )
    avoid_cases: list[str] = Field(
        default_factory=list,
        description="禁忌场景列表",
    )
    is_system: bool = Field(..., description="系统模板标记")
    sort_order: int = Field(..., description="UI 显示排序（升序）")
    created_at: datetime = Field(..., description="入库时间")


class CtaPatternRead(BaseModel):
    """CtaPattern 只读响应。

    用于 ``GET /api/v1/studio/cta-patterns`` 列表与详情。``hardness`` 与
    ``urgency_type`` 同时暴露，供前端做双轴筛选。
    """

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="CTA ID（如 scarcity_cta）")
    name: str = Field(..., description="中文名称（如 稀缺紧迫）")
    hardness: str = Field(..., description="硬度等级：soft / medium / hard")
    urgency_type: str = Field(
        ...,
        description="驱动类型：scarcity / urgency / social_proof / benefit / risk_removal",
    )
    description: str = Field(..., description="CTA 说明（运营/UI 展示）")
    template_text: str = Field(..., description="Jinja2 模板片段")
    sample_phrases: list[str] = Field(
        default_factory=list,
        description="样例 CTA 短语列表",
    )
    is_system: bool = Field(..., description="系统模板标记")
    sort_order: int = Field(..., description="UI 显示排序（升序）")
    created_at: datetime = Field(..., description="入库时间")


class BrandArchetypeRead(BaseModel):
    """BrandArchetype 只读响应。

    用于 ``GET /api/v1/studio/brand-archetypes`` 列表与详情。
    ``voice_traits`` / ``speech_patterns`` / ``sample_brands`` 三个 JSON
    列保留原始结构，前端原型卡片可直接渲染 do/dont 与代表品牌。

    注：``voice_traits`` 在 ORM 中以 ``list[str]`` 存储，但本响应将其暴
    露为 ``dict[str, Any]`` 以兼容上游期望（见 W14-T4 OUTCOME 规约）。
    实际由 :class:`app.services.commerce.pattern_library.PatternLibraryService`
    在序列化时按需包裹，避免 schema 与 ORM 列形状强耦合。
    """

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="原型 ID（如 sage / jester）")
    name: str = Field(..., description="英文名称（Sage / Jester / ...）")
    name_zh: str = Field(..., description="中文名称（智者 / 小丑 / ...）")
    motivation: str = Field(..., description="核心动机（80-150 字）")
    voice_traits: dict[str, Any] = Field(
        default_factory=dict,
        description="语调描述符，结构 {items: [...]}",
    )
    speech_patterns: dict[str, Any] = Field(
        default_factory=dict,
        description="语言模式 JSON：{do: [...], dont: [...]}",
    )
    sample_brands: list[str] = Field(
        default_factory=list,
        description="代表品牌列表",
    )
    is_system: bool = Field(..., description="系统原型标记")
    sort_order: int = Field(..., description="UI 显示排序（升序）")
    created_at: datetime = Field(..., description="入库时间")


__all__ = [
    "HookPatternRead",
    "CtaPatternRead",
    "BrandArchetypeRead",
]
