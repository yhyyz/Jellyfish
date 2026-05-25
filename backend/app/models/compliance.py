"""合规管理相关 ORM 模型（W2-T3）。

本模块定义剧情带货合规检查链路所需的两类实体：

- :class:`ComplianceProfile`：按地域+品类聚合的合规规则集，作为脚本/视频
  发布前校验的规则源；系统预置版本不可删除。
- :class:`ComplianceFinding`：单次合规检查在某个 :class:`StoryVariant`
  上发现的具体问题，作为下游修复/复查的工作单元。

注意：
- :class:`ComplianceFinding.variant_id` 通过字符串 FK 引用
  ``story_variants.id``，运行时由 SQLAlchemy 解析；本模块不直接 import
  :class:`StoryVariant`，避免与 W2-T2 的提交顺序耦合。
- 与 :class:`StoryVariant` 的反向 ``relationship`` 由 W2-T2 负责（如需），
  本模块仅保留出向 FK，不在此处建立反向 backref。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin
from app.models.types import ComplianceRegion, ComplianceSeverity


class ComplianceProfile(Base, TimestampMixin):
    """合规规则集 — 按地域+品类分组。

    用于在剧情带货发布前对脚本/视频做合规校验。每个 profile 是一组规则
    的集合，按地域（``region``）切换；``is_system=True`` 表示系统预置版本，
    不允许业务侧删除，仅可派生新副本。

    主要字段说明：
    - ``id``：稳定字符串 ID（如 ``cn_mainland_default``、``cn_mainland_health``、
      ``overseas_default``），便于在配置/代码中引用。
    - ``rules``：规则数组的 JSON，每条规则典型包含 ``id``/``kind``/
      ``severity``/``pattern``/``cap`` 等字段，由调用方解析。
    """

    __tablename__ = "compliance_profiles"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        comment="profile ID（如 cn_mainland_default、cn_mainland_health、overseas_default）",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="显示名称",
    )
    region: Mapped[ComplianceRegion] = mapped_column(
        String(16),
        nullable=False,
        default=ComplianceRegion.cn_mainland.value,
        server_default=ComplianceRegion.cn_mainland.value,
        index=True,
        comment="适用地域",
    )
    rules: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="规则数组 JSON（每条含 id/kind/severity/pattern/cap 等字段）",
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
        comment="系统预置",
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
        comment="profile 用途说明",
    )


class ComplianceFinding(Base, TimestampMixin):
    """合规检查产出的具体问题。

    一个 :class:`StoryVariant` 可关联 N 条 finding，按 ``severity`` 决定
    是否阻塞发布（``blocker`` 必须修复）。``rule_id`` / ``rule_kind`` 指向
    触发规则，``location`` 指向脚本中的具体位置（如 ``"Shot 3, dialog
    line 2"``），便于编辑器快速定位修复。

    与 :class:`StoryVariant` 的关系通过字符串 FK ``story_variants.id``
    建立，删除变体时级联清理对应 finding。
    """

    __tablename__ = "compliance_findings"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    variant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("story_variants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属脚本变体",
    )
    severity: Mapped[ComplianceSeverity] = mapped_column(
        String(16),
        nullable=False,
        default=ComplianceSeverity.warning.value,
        server_default=ComplianceSeverity.warning.value,
        index=True,
        comment="严重度",
    )
    rule_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="触发的规则 ID",
    )
    rule_kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="banned_phrase",
        server_default="banned_phrase",
        comment="规则类型：banned_phrase/required_label/required_disclaimer/brand_mention_cap",
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="问题描述",
    )
    location: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        default=None,
        comment="脚本中位置（如 'Shot 3, dialog line 2'）",
    )
    suggested_fix: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="建议修复方案",
    )
    is_resolved: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
        index=True,
        comment="是否已解决",
    )
    detected_at: Mapped[datetime] = mapped_column(
        nullable=False,
        comment="检测时间",
    )

    __table_args__ = (
        Index(
            "ix_compliance_findings_variant_severity",
            "variant_id",
            "severity",
        ),
    )


__all__ = [
    "ComplianceProfile",
    "ComplianceFinding",
]
