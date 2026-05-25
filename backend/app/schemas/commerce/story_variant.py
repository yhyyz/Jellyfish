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
    "StoryVariantCreate",
    "StoryVariantRead",
]
