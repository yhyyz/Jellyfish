"""品牌话术规范库（BrandStyleGuide）模型 —— W25-T3，P4 Wave A。

为每个商品（``Product``）提供一份可选的"品牌话术规范"，承载：

* ``forced_phrases``：强制金句列表（脚本/对白生成阶段必须包含的短语）；
* ``banned_patterns``：禁用句式列表（生成器需回避的措辞 / 句式 pattern）；
* ``required_endings``：必备结尾列表（CTA 收尾或免责声明等强制收口短语）；
* ``brand_persona_tagline``：一句话品牌人格短描述（用于 LLM system prompt
  注入，区分品牌调性，不与 ``BrandArchetype`` 注册表冲突——后者是系统级
  原型库，本字段是品牌侧的自由短描述）。

设计要点：

* 与 ``Product`` 形成 **1:1 可选** 关系：``product_id`` 既是 FK 又是
  ``UNIQUE``，等价于 "至多一份规范挂在某个商品上"。建表时即可在
  ``ON DELETE CASCADE`` 下保证商品删除时同步清理本表行。
* P4-T25-3 仅落地数据基础设施；T25-1 / T25-2 引入的 LLM validator 后续
  会读这张表（本任务不做集成），所以这里不预置任何业务方法。
* 所有 JSON list 字段允许空数组，``brand_persona_tagline`` 允许空串，
  让前端可以在还未补齐内容时也能保存草稿。
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin


class BrandStyleGuide(Base, TimestampMixin):
    """品牌话术规范（与 Product 1:1，可选）。

    字段语义见模块 docstring。``product_id`` 同时担任：

    * 外键 → ``products.id``（``ON DELETE CASCADE``）；
    * 唯一约束（``uq_brand_style_guides_product_id``）→ 1:1 语义。

    ``id`` 仍单独作为字符串主键，便于路由层在不暴露 product_id 复合键
    的前提下继续使用统一的 entity-id 风格（与 ``CommerceStoryConfig``
    把 ``project_id`` 当主键不同：本表对外暴露的子资源路径是
    ``/products/{product_id}/brand-style-guide`` 而非 ``/brand-style-guides/{id}``，
    所以 ``id`` 仅做内部稳定标识）。
    """

    __tablename__ = "brand_style_guides"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        comment="规范 ID（uuid4 hex，由 service 层生成）",
    )
    product_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
        comment="所属商品 ID（1:1，UNIQUE + CASCADE）",
    )
    forced_phrases: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="强制金句列表（生成器必须包含的短语）",
    )
    banned_patterns: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="禁用句式列表（生成器需回避的措辞）",
    )
    required_endings: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="必备结尾列表（CTA / 免责声明类强制收口短语）",
    )
    brand_persona_tagline: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
        server_default="",
        comment="品牌人格短描述（一句话 tagline，用于 LLM system prompt 注入）",
    )

    __table_args__ = (
        UniqueConstraint(
            "product_id",
            name="uq_brand_style_guides_product_id",
        ),
    )


__all__ = ["BrandStyleGuide"]
