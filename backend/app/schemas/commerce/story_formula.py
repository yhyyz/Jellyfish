"""StoryFormula 只读响应 schemas（W6-T2，P1 阶段）。

只读语义：
- 公式注册表是系统级种子数据（``is_system=True``），由
  :func:`app.services.commerce.builtin_story_formulas.bootstrap_builtin_story_formulas`
  在启动期幂等加载，应用层接口不允许新增/编辑/删除。
- 因此本模块只暴露读取所需 DTO（``StoryFormulaBeatRead`` /
  ``StoryFormulaStructureRead`` / ``StoryFormulaRead``），不提供
  Create/Update。

字段语义对齐 :class:`app.models.story_formula.StoryFormula`，并把
``structure`` JSON 列拆解成结构化嵌套（``beats`` / ``total_shots_range``
/ ``duration_sec_range``），让前端列表与详情页可以直接消费而无需再做
二次解析。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.types import FormulaRegion


class StoryFormulaBeatRead(BaseModel):
    """单个叙事节拍（beat）只读视图。

    与 :class:`app.services.commerce.builtin_story_formulas.Beat` 字段对齐，
    用于前端逐条渲染镜头组。
    """

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="节拍唯一名（snake_case）")
    duration_sec: int = Field(..., description="本节拍占用秒数")
    function: str = Field(..., description="本节拍承担的叙事功能")
    shot_type: str = Field(..., description="建议景别")
    recommended_camera_movement: str | None = Field(
        None,
        description="建议运镜（None 表示静态）",
    )


class StoryFormulaStructureRead(BaseModel):
    """``structure`` JSON 列的结构化只读视图。

    把数据库内 ``structure`` JSON 内容拆为类型化字段，避免前端反复做
    弱类型 JSON 解析。同时保留 ``Tuple`` 转 ``list[int]`` 的容忍：
    ``bootstrap_builtin_story_formulas.to_structure_payload`` 会写入
    ``[a, b]`` 形式（``list``），与 ORM 读出来的 JSON 表现一致。
    """

    beats: list[StoryFormulaBeatRead] = Field(
        default_factory=list,
        description="叙事节拍数组",
    )
    total_shots_range: list[int] = Field(
        default_factory=list,
        description="典型镜头数范围 [min, max]",
    )
    duration_sec_range: list[int] = Field(
        default_factory=list,
        description="典型时长范围（秒）[min, max]",
    )


class StoryFormulaRead(BaseModel):
    """StoryFormula 只读响应。

    字段与 ORM 列对齐；``structure`` 单独从 JSON 列拆解出嵌套结构，便于
    前端直接渲染节拍。``risk_flags`` / ``use_cases`` / ``avoid_cases``
    保持原始 ``list[str]``，与种子数据格式一致。
    """

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="公式 ID（如 underdog_triumph）")
    name: str = Field(..., description="中文名称")
    region: FormulaRegion = Field(..., description="适用地域：cn / global")
    category: str = Field(..., description="分类标签")
    structure: StoryFormulaStructureRead = Field(
        ...,
        description="完整 beat 结构（含 beats 数组、镜头数与时长范围）",
    )
    risk_flags: list[str] = Field(
        default_factory=list,
        description="合规风险标记数组",
    )
    sample_dialog: str = Field(..., description="完整示例剧本（变量化）")
    typical_duration_sec: int = Field(..., description="典型时长（秒）")
    typical_shot_count: int = Field(..., description="典型镜头数")
    psychology: str = Field(..., description="心理学原理：为什么有效")
    use_cases: list[str] = Field(
        default_factory=list,
        description="适用场景",
    )
    avoid_cases: list[str] = Field(
        default_factory=list,
        description="禁忌场景",
    )
    prompt_template_id: str = Field(..., description="绑定的提示词模板 ID")
    is_system: bool = Field(..., description="系统模板标记，应用层不可删除")
    sort_order: int = Field(..., description="UI 显示排序（升序）")


__all__ = [
    "StoryFormulaBeatRead",
    "StoryFormulaStructureRead",
    "StoryFormulaRead",
]
