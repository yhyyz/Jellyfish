"""剧情带货项目（kind=commerce_story）的请求/响应 schemas（W6-T2，P1 阶段）。

设计要点：

- ``StoryProjectCreate`` 把 :class:`app.models.studio.Project` 核心字段与
  :class:`app.models.commerce_assets.CommerceStoryConfig` 配置字段聚合为
  单一请求体；服务层在单事务内同时落库（W6-T2 业务约束）。
- 创建请求中 ``kind`` 不接受客户端传入：服务层强制写为
  ``ProjectKind.commerce_story``，避免普通 drama 项目被误归类。
- ``StoryProjectConfigUpdate`` 仅承载 CommerceStoryConfig 字段，且全部为
  可选；Project 核心字段（name/description/style 等）由现有
  ``/api/v1/studio/projects`` PATCH 走相同路径维护，避免双入口造成边界
  混乱。
- ``StoryProjectRead`` 平铺 Project + CommerceStoryConfig，方便前端单次
  请求拿到详情；用 ``ConfigDict(from_attributes=True)`` 让 ORM 实例可直
  接 ``model_validate``。
- ``ProjectProductLinkCreate``/``ProjectProductLinkRead`` 对齐
  :class:`app.models.commerce_assets.ProjectProductLink` 的字段，仅暴露
  link/unlink 路径所需子集（不复用 W6-T1 的 product CRUD schema）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.types import (
    ComplianceRegion,
    Platform,
    ProductAppearanceTiming,
    ProductRoleInStory,
    ProjectStyle,
    ProjectVisualStyle,
)


class CommerceStoryConfigBase(BaseModel):
    """CommerceStoryConfig 创建/读取共享字段。"""

    target_platform: Platform = Field(
        Platform.douyin,
        description="目标平台",
    )
    target_duration_sec: int = Field(
        60,
        ge=1,
        description="目标时长（秒）",
    )
    formula_id: str | None = Field(
        None,
        description="选定的剧情公式 ID（StoryFormula.id）",
    )
    archetype: str | None = Field(
        None,
        description="品牌人格 archetype（P2 启用 BrandArchetype 枚举）",
    )
    tone_grid: dict[str, Any] = Field(
        default_factory=dict,
        description="语调维度 JSON",
    )
    audience_override: dict[str, Any] | None = Field(
        None,
        description="覆盖商品默认受众的项目级配置",
    )
    compliance_region: ComplianceRegion = Field(
        ComplianceRegion.cn_mainland,
        description="合规地域",
    )
    compliance_profile_id: str = Field(
        "cn_mainland_default",
        description="合规规则集 ID",
    )
    target_kpi: str | None = Field(
        None,
        description="目标 KPI: awareness/clicks/conversion",
    )


class CommerceStoryConfigRead(CommerceStoryConfigBase):
    """CommerceStoryConfig 只读视图（嵌入 StoryProjectRead）。"""

    model_config = ConfigDict(from_attributes=True)

    project_id: str = Field(..., description="所属项目 ID")


def _default_commerce_story_config() -> "CommerceStoryConfigBase":
    """``StoryProjectCreate.config`` 的默认值工厂。

    单独抽出函数（而非直接传 ``CommerceStoryConfigBase`` 类对象给
    ``default_factory``）有两个目的：

    - 让静态类型检查器把它识别为零参 ``Callable``，避免误判
      ``default_factory`` 签名。
    - 显式利用 :class:`CommerceStoryConfigBase` 在 :mod:`pydantic` 上的
      字段默认值，构造一个完整的、所有字段都已 default 化的实例，
      ``StoryProjectCreate`` 在客户端不传 ``config`` 时即得到稳定形态。
    """
    return CommerceStoryConfigBase.model_construct()


class StoryProjectCreate(BaseModel):
    """创建 commerce_story 项目请求体。

    同时承载 Project 核心字段与 CommerceStoryConfig 字段；服务层在单事务
    内完成两表 INSERT，并强制 ``kind=commerce_story``。
    """

    # Project 核心字段（不含 kind，由服务端强制注入）
    id: str = Field(..., description="项目 ID（业务方生成或外部生成）")
    name: str = Field(..., description="项目名称")
    description: str = Field("", description="项目简介")
    style: ProjectStyle = Field(
        ProjectStyle.real_people_city,
        description="题材/风格",
    )
    visual_style: ProjectVisualStyle = Field(
        ProjectVisualStyle.live_action,
        description="画面表现形式（真人/动漫等）",
    )
    seed: int = Field(0, description="随机种子")
    unify_style: bool = Field(True, description="是否统一风格（跨章节）")
    progress: int = Field(0, ge=0, le=100, description="进度百分比")
    default_video_ratio: str | None = Field(
        None,
        description="项目级默认视频比例",
    )
    stats: dict[str, Any] = Field(
        default_factory=dict,
        description="聚合统计（JSON）",
    )

    # CommerceStoryConfig 字段
    config: CommerceStoryConfigBase = Field(
        default_factory=_default_commerce_story_config,
        description="带货项目专属配置",
    )


class StoryProjectConfigUpdate(BaseModel):
    """更新 CommerceStoryConfig（不含 Project 核心字段）。

    全部字段可选，按 ``model_dump(exclude_unset=True)`` 增量 patch。
    """

    target_platform: Platform | None = None
    target_duration_sec: int | None = Field(None, ge=1)
    formula_id: str | None = None
    archetype: str | None = None
    tone_grid: dict[str, Any] | None = None
    audience_override: dict[str, Any] | None = None
    compliance_region: ComplianceRegion | None = None
    compliance_profile_id: str | None = None
    target_kpi: str | None = None


class StoryProjectRead(BaseModel):
    """commerce_story 项目详情：Project 核心 + CommerceStoryConfig。

    ``config`` 可能为空：当历史数据未补齐时（理论上不应出现，但保留容
    错），列表 / 详情接口仍然可用。
    """

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="项目 ID")
    name: str = Field(..., description="项目名称")
    description: str = Field("", description="项目简介")
    style: ProjectStyle = Field(..., description="题材/风格")
    visual_style: ProjectVisualStyle = Field(..., description="画面表现形式")
    seed: int = Field(..., description="随机种子")
    kind: str = Field(..., description="项目类型（固定为 commerce_story）")
    unify_style: bool = Field(..., description="是否统一风格")
    progress: int = Field(..., description="进度百分比")
    default_video_ratio: str | None = Field(None, description="项目级默认视频比例")
    stats: dict[str, Any] = Field(default_factory=dict, description="聚合统计")
    config: CommerceStoryConfigRead | None = Field(
        None,
        description="带货项目专属配置（1:1）",
    )


class ProjectProductLinkCreate(BaseModel):
    """商品关联创建请求体。

    路径参数已经携带 ``project_id`` 与 ``product_id``，因此 body 只承载
    剧情节奏控制字段；``chapter_id``/``shot_id`` 在 P1 留空（项目级
    挂载），后续阶段如需更细粒度可在 body 内扩展。
    """

    role_in_story: ProductRoleInStory = Field(
        ProductRoleInStory.savior,
        description="商品在剧情中的角色",
    )
    appearance_timing: ProductAppearanceTiming = Field(
        ProductAppearanceTiming.middle,
        description="出现时机",
    )
    appearance_duration_sec: int = Field(
        5,
        ge=1,
        description="出现时长（秒）",
    )


class ProjectProductLinkRead(BaseModel):
    """商品关联只读视图。"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="自增主键")
    project_id: str = Field(..., description="项目 ID")
    chapter_id: str | None = Field(None, description="章节 ID（P1 留空）")
    shot_id: str | None = Field(None, description="镜头 ID（P1 留空）")
    product_id: str = Field(..., description="商品 ID")
    role_in_story: ProductRoleInStory = Field(..., description="角色")
    appearance_timing: ProductAppearanceTiming = Field(..., description="时机")
    appearance_duration_sec: int = Field(..., description="时长（秒）")


__all__ = [
    "CommerceStoryConfigBase",
    "CommerceStoryConfigRead",
    "StoryProjectCreate",
    "StoryProjectConfigUpdate",
    "StoryProjectRead",
    "ProjectProductLinkCreate",
    "ProjectProductLinkRead",
]
