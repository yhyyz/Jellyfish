"""StoryVariant 请求/响应 schemas（W6-T2，P1 阶段）。

P1 仅支持 **手动创建**（前端发起一次"生成变体"动作即一条记录），不暴
露自动化生成入口。冠军变体标记 ``is_champion`` 与钩子模式
``hook_pattern_id`` / ``cta_pattern_id`` 全部为 P2 预留字段，本期只读、
不允许通过创建接口写入：

- 创建路径：服务层强制 ``status=draft`` / ``is_champion=False`` /
  ``compliance_score=0``；客户端只能传必填业务字段（project_id /
  chapter_id / formula_id / script_full_text / script_breakdown）以及
  生成上下文（``generated_by_task_id``、可选的 ``archetype``）。
- 列表路径：``project_id`` 必填，按 ``created_at desc`` 排序，可选按
  ``chapter_id`` / ``status`` 过滤。

字段语义对齐 :class:`app.models.story_formula.StoryVariant`，
``StoryVariantStatus`` 枚举与运行时任务体系共用。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.types import StoryVariantStatus


class StoryVariantCreate(BaseModel):
    """手动创建 StoryVariant 的请求体。

    ``id`` 由服务层生成（``uuid4().hex``），不接受客户端传入。
    ``status`` / ``is_champion`` / ``compliance_score`` 同样由服务端固
    定，避免客户端绕过 A/B 评估机制提前置位。
    """

    project_id: str = Field(..., min_length=1, description="所属项目 ID")
    chapter_id: str = Field(..., min_length=1, description="所属章节 ID")
    formula_id: str = Field(..., min_length=1, description="使用的剧情公式 ID")
    script_full_text: str = Field(..., description="完整剧本文本")
    script_breakdown: dict[str, Any] = Field(
        default_factory=dict,
        description="镜头分解结果 JSON",
    )
    archetype: str | None = Field(
        None,
        description="品牌人格 archetype（P2 启用 BrandArchetype 枚举）",
    )
    generated_by_task_id: str | None = Field(
        None,
        description="生成此变体的 GenerationTask ID（无硬 FK）",
    )


class StoryVariantCloneRequest(BaseModel):
    """克隆变体的请求体；可选覆盖字段（W14-T3，A/B 变体管理）。

    用于 ``POST /story-variants/{id}/clone`` 接口：基于已有变体快速派生一
    个新的 ``draft`` 变体，业务方可在克隆同时调整 ``archetype`` /
    ``hook_pattern_id`` / ``cta_pattern_id`` / ``formula_id`` 等关键 A/B
    维度，无需重复传递剧本文本与镜头分解。

    设计要点：

    * ``extra="forbid"``：阻止客户端通过未知字段（例如 ``status``、
      ``is_champion``、``compliance_score``）绕过服务端固定值，保持与
      :class:`StoryVariantCreate` 一致的"只读字段"语义。
    * 全部字段可选（``None`` 即 "保持源变体值"），调用方仅传需要变更的
      维度即可触发针对性 A/B；``label`` 仅作业务备注，不写库。
    """

    model_config = ConfigDict(extra="forbid")

    new_archetype: str | None = Field(
        None,
        description="覆盖 archetype（None 表示保持源变体）",
    )
    new_hook_pattern_id: str | None = Field(
        None,
        description="覆盖 hook_pattern_id（P2 钩子模式 A/B）",
    )
    new_cta_pattern_id: str | None = Field(
        None,
        description="覆盖 cta_pattern_id（P2 CTA 模式 A/B）",
    )
    new_formula_id: str | None = Field(
        None,
        description="覆盖 formula_id（切换剧情公式做更激进的 A/B）",
    )
    label: str | None = Field(
        None,
        description="备注，仅供调用方记录派生意图，不会写入数据库",
    )


class StoryVariantRead(BaseModel):
    """StoryVariant 只读响应。

    暴露 P1 业务关心的全部字段；P2 预留字段（``hook_pattern_id`` /
    ``cta_pattern_id`` / ``is_champion``）作为只读返回，前端可在 P2
    UI 下分阶段启用。
    """

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="变体唯一 ID")
    project_id: str = Field(..., description="所属项目")
    chapter_id: str = Field(..., description="所属章节")
    formula_id: str = Field(..., description="使用的剧情公式 ID")
    hook_pattern_id: str | None = Field(None, description="钩子模式 ID（P2）")
    cta_pattern_id: str | None = Field(None, description="CTA 模式 ID（P2）")
    archetype: str | None = Field(None, description="品牌人格")
    script_full_text: str = Field(..., description="完整剧本文本")
    script_breakdown: dict[str, Any] = Field(
        default_factory=dict,
        description="镜头分解结果 JSON",
    )
    status: StoryVariantStatus = Field(..., description="状态")
    is_champion: bool = Field(..., description="是否冠军变体（P2）")
    compliance_score: int = Field(..., description="合规评分 0-100")
    generated_by_task_id: str | None = Field(
        None,
        description="生成此变体的 GenerationTask ID",
    )
    created_at: datetime | None = Field(None, description="创建时间")
    updated_at: datetime | None = Field(None, description="最近更新时间")


__all__ = [
    "StoryVariantCloneRequest",
    "StoryVariantCreate",
    "StoryVariantRead",
]
