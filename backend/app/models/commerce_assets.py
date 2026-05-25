"""剧情带货（Story-Driven Commerce）相关 ORM 模型。

设计要点：
- 结构上镜像现有 Prop / PropImage / ProjectPropLink 三件套，
  但语义上承载"商品"概念：可跨项目复用的商业资源。
- D1 决策：Product.name 在全库范围内唯一（与 Prop 一致），
  不做项目级 scope，便于跨项目去重与素材复用。
- 与项目的关联走 ProjectProductLink，可挂在 project / chapter / shot
  任一层；CommerceStoryConfig 与 Project 形成 1:1 配置表。
- 不在此处定义合规规则集 / 故事公式 / 受众画像表（见 W2-T2/T3/T4）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin
from app.models.types import (
    AssetQualityLevel,
    AssetViewAngle,
    ComplianceRegion,
    Platform,
    ProductAppearanceTiming,
    ProductCategory,
    ProductRoleInStory,
    ProjectStyle,
    ProjectVisualStyle,
)

if TYPE_CHECKING:  # pragma: no cover - 仅为类型注解使用
    pass


class Product(Base, TimestampMixin):
    """商品主体 — 剧情带货项目中的"故事主角"实体。

    结构镜像 Prop（同样具备 name/description/style/visual_style/prompt_template_id），
    但语义更偏向商业资源：可在多个项目间复用，承载品牌、定价、卖点、
    目标受众、金句、合规相关字段，作为生成器（脚本/文案/合规）的输入根。

    约束：
    - `name` 全库唯一（D1 决策，与 Prop 一致），便于跨项目素材去重。
    - 关联 `prompt_template_id` 用于商品级提示词模板复用，可空。
    """

    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="商品唯一标识")
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="商品名称")
    brand: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="",
        server_default="",
        comment="品牌",
    )
    category: Mapped[ProductCategory] = mapped_column(
        String(32),
        nullable=False,
        default=ProductCategory.other.value,
        server_default=ProductCategory.other.value,
        index=True,
        comment="商品分类（电子/美妆/食品/服饰/家居/健康/其他）",
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
        comment="商品描述/卖点摘要",
    )
    price_anchor: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        default=None,
        comment="锚定价（人民币）；用于脚本/文案中提及参考价",
    )
    sku: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        default=None,
        comment="SKU / 货号（可空）",
    )
    selling_points: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="卖点列表（JSON 数组，建议 ≤5）",
    )
    pain_points_solved: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="解决的痛点（JSON 数组）",
    )
    target_audience: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="目标受众 JSON：{age_range, gender, region_tier, pain_points}",
    )
    catchphrases: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="金句台词列表（用于嵌入剧情对白）",
    )
    competitor_names: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="禁止提及的竞品名列表（合规检查使用）",
    )
    health_disclaimer_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
        comment="是否需要健康类免责声明（health 品类常需）",
    )
    visual_style: Mapped[ProjectVisualStyle] = mapped_column(
        String(16),
        nullable=False,
        default=ProjectVisualStyle.live_action.value,
        server_default=ProjectVisualStyle.live_action.value,
        comment="视觉风格（现实/动漫等）",
    )
    style: Mapped[ProjectStyle] = mapped_column(
        String(32),
        nullable=False,
        default=ProjectStyle.real_people_city.value,
        server_default=ProjectStyle.real_people_city.value,
        comment="题材风格（与 ProjectStyle 共用枚举）",
    )
    prompt_template_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("prompt_templates.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
        index=True,
        comment="关联提示词模板 ID（可空）",
    )

    # 多角度图片，cascade 与 Prop 一致
    images: Mapped[list["ProductImage"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ProductImage.id",
    )

    __table_args__ = (
        Index("ix_products_name", "name"),
        # D1: 与 Prop 一致，name 全局唯一，不做项目 scope
        UniqueConstraint("name", name="uq_products_name"),
    )


class ProductImage(Base, TimestampMixin):
    """商品多角度图片 — 镜像 PropImage 结构。

    每个 (product_id, quality_level, view_angle) 仅允许一张图，
    便于按精度等级与视角进行幂等替换；is_primary 在应用层保证单值。
    """

    __tablename__ = "product_images"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="自增主键",
    )
    product_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属商品 ID",
    )
    file_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="关联文件 ID（可空，支持先创建槽位后填充）",
    )
    quality_level: Mapped[AssetQualityLevel] = mapped_column(
        String(16),
        nullable=False,
        default=AssetQualityLevel.low.value,
        server_default=AssetQualityLevel.low.value,
        index=True,
        comment="质量等级（LOW/MEDIUM/HIGH/ULTRA）",
    )
    view_angle: Mapped[AssetViewAngle] = mapped_column(
        String(32),
        nullable=False,
        default=AssetViewAngle.front.value,
        server_default=AssetViewAngle.front.value,
        index=True,
        comment="视角（FRONT/LEFT/RIGHT/...）",
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
        comment="是否主图；应用层保证同一 product_id 下至多一张",
    )
    width: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        default=None,
        comment="宽（像素）",
    )
    height: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        default=None,
        comment="高（像素）",
    )
    fmt: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        default=None,
        comment="格式（jpg/png/webp）",
    )

    product: Mapped["Product"] = relationship(back_populates="images")

    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "quality_level",
            "view_angle",
            name="uq_product_images_quality_angle",
        ),
    )


class ProjectProductLink(Base, TimestampMixin):
    """项目-商品多对多关联，可挂在 project / chapter / shot 任一层。

    设计与 ProjectPropLink 镜像：通过组合 (project_id, chapter_id, shot_id)
    支持不同粒度挂载；唯一约束保证同一商品在同一作用域内不重复。
    role_in_story / appearance_timing / appearance_duration_sec 用于指导
    脚本生成与剧情节奏控制。
    """

    __tablename__ = "project_product_links"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="自增主键",
    )
    project_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="项目 ID（必填）",
    )
    chapter_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("chapters.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
        index=True,
        comment="章节 ID（可选）",
    )
    shot_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("shots.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
        index=True,
        comment="镜头 ID（可选）",
    )
    product_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="商品 ID",
    )
    role_in_story: Mapped[ProductRoleInStory] = mapped_column(
        String(32),
        nullable=False,
        default=ProductRoleInStory.savior.value,
        server_default=ProductRoleInStory.savior.value,
        comment="商品在剧情中的角色（savior/catalyst/...）",
    )
    appearance_timing: Mapped[ProductAppearanceTiming] = mapped_column(
        String(16),
        nullable=False,
        default=ProductAppearanceTiming.middle.value,
        server_default=ProductAppearanceTiming.middle.value,
        comment="出现时机（opening/middle/climax/ending）",
    )
    appearance_duration_sec: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5,
        server_default="5",
        comment="出现时长（秒）",
    )

    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "project_id",
            "chapter_id",
            "shot_id",
            name="uq_project_product_links_scope",
        ),
    )


class CommerceStoryConfig(Base, TimestampMixin):
    """剧情带货项目专属配置（与 Project 1:1）。

    存储项目级带货配置：投放平台、目标时长、所选剧情公式、品牌人格、
    语调维度、合规地域与规则集等；archetype / tone_grid 在 P1 仅做存储，
    P2 再启用 BrandArchetype 枚举与完整语调维度。
    """

    __tablename__ = "commerce_story_configs"

    project_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
        comment="项目 ID（PK，1:1）",
    )
    target_platform: Mapped[Platform] = mapped_column(
        String(32),
        nullable=False,
        default=Platform.douyin.value,
        server_default=Platform.douyin.value,
        comment="目标平台（douyin/kuaishou/...）",
    )
    target_duration_sec: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=60,
        server_default="60",
        comment="目标时长（秒）",
    )
    formula_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        default=None,
        index=True,
        comment="选定的剧情公式 ID（StoryFormula.id，W2-T3）",
    )
    archetype: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        default=None,
        comment="品牌人格 archetype（P2 启用 BrandArchetype 枚举）",
    )
    tone_grid: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="语调维度 JSON（P2 完整启用）",
    )
    audience_override: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
        comment="覆盖商品默认受众的项目级配置",
    )
    compliance_region: Mapped[ComplianceRegion] = mapped_column(
        String(16),
        nullable=False,
        default=ComplianceRegion.cn_mainland.value,
        server_default=ComplianceRegion.cn_mainland.value,
        comment="合规地域",
    )
    compliance_profile_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="cn_mainland_default",
        server_default="cn_mainland_default",
        comment="合规规则集 ID",
    )
    target_kpi: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        default=None,
        comment="目标 KPI: awareness/clicks/conversion",
    )


__all__ = [
    "Product",
    "ProductImage",
    "ProjectProductLink",
    "CommerceStoryConfig",
]
