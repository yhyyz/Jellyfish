"""CTA 模式（CtaPattern）模型 —— W11-T2，P2 启用前的注册表。

本文件提供一张系统级"CTA（Call-to-Action）模式"注册表 :class:`CtaPattern`，
用于管理 P2 阶段会启用的 5 种短视频收尾 CTA（``scarcity_cta`` /
``social_proof_cta`` / ``benefit_direct_cta`` / ``risk_removal_cta`` /
``urgency_simple_cta``）。

设计要点：

* 双轴定位：``hardness`` 表达"语气硬度"（``soft`` / ``medium`` / ``hard``），
  ``urgency_type`` 表达"驱动类型"（``scarcity`` / ``urgency`` /
  ``social_proof`` / ``benefit`` / ``risk_removal``）。两轴正交，便于运营
  在不同阶段（高客单/低客单/直播尾部/转化卡片）选用不同 CTA；
* ``sample_phrases`` 用 JSON 数组承载 5-10 条样例 CTA 短语，避免单一模板
  导致投放风格雷同；
* 与 :class:`HookPattern` 一样不在本期为 ``StoryVariant.cta_pattern_id``
  加硬外键，预留给 P2 集成阶段；
* ``is_system=True`` 由内置 bootstrap 幂等写入，禁止应用层直接删除。
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin


class CtaPattern(Base, TimestampMixin):
    """CTA 模式注册表 —— P2 启用，5 种 hardness × urgency_type 组合。

    每条记录定义一种"如何收尾促转化"的 CTA 模板。两个分类轴：

    * ``hardness``：``soft`` / ``medium`` / ``hard`` —— 表达 CTA 在画面/语
      气上的强烈程度，影响品牌调性；
    * ``urgency_type``：驱动机制 —— ``scarcity``（库存稀缺）/ ``urgency``
      （时间窗）/ ``social_proof``（从众）/ ``benefit``（直击利益）/
      ``risk_removal``（去除风险）。

    系统模板 (``is_system=True``) 由 :func:`bootstrap_builtin_cta_patterns`
    写入；与 :class:`HookPattern` 共享同款"运营资产"语义。
    """

    __tablename__ = "cta_patterns"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        comment="CTA ID（如 scarcity_cta / social_proof_cta）",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="中文名称（如 稀缺紧迫）",
    )
    hardness: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        index=True,
        comment="硬度等级：soft / medium / hard",
    )
    urgency_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        comment="驱动类型：scarcity / urgency / social_proof / benefit / risk_removal",
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
        comment="CTA 说明（运营/UI 展示，~80-150 字）",
    )
    template_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
        comment="Jinja2 模板片段（LLM 渲染收尾用）",
    )
    sample_phrases: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="样例 CTA 短语列表（5-10 条）",
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
        comment="系统模板，不可删除",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="UI 显示排序（升序）",
    )


__all__ = ["CtaPattern"]
