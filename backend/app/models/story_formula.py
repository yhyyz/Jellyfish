"""Story-Driven Commerce 剧情带货核心模型（W2-T2，P1 阶段）。

本模块定义剧情带货功能在 P1 阶段必需的 3 张表：

- :class:`StoryFormula`：系统级剧情公式注册表（如"凡人逆袭""开局打脸"等
  叙事模板）。每条记录定义完整的 beats 结构、风险标记、心理学解释、典型
  时长与镜头数，并绑定一个生成提示词模板。``is_system=True`` 表示该公式
  来自内置初始化脚本，禁止通过应用层接口删除/编辑。
- :class:`StoryVariant`：项目/章节下的脚本变体。同一项目可生成多个 A/B
  变体（基于不同公式或参数），P1 仅支持手动创建并持久化生成结果；
  ``hook_pattern_id`` / ``cta_pattern_id`` / ``archetype`` / ``is_champion``
  字段为 P2 钩子模式 + 品牌人格 + A/B 优胜机制预留。
- :class:`StoryOutcome`：每个变体的真实投放效果数据（播放量、完播率、
  GMV 等）。P1 仅创建表保留扩展空间；P3 启用录入和分析。

设计要点：

* 三表全部使用 :class:`~app.models.base.TimestampMixin`，与项目其他表保持
  一致的 ``created_at`` / ``updated_at`` 行为。
* 全部使用项目惯例的 ``Mapped[...] = mapped_column(...)`` SQLAlchemy 2.x
  风格，与 ``studio_projects`` / ``studio_assets`` 等模块对齐。
* ``StoryOutcome.plays`` 选用 :class:`~sqlalchemy.BigInteger`，因为爆款
  视频的播放量极易突破 ``2^31``，避免后续再做迁移。
* ``StoryOutcome.raw_payload`` 保留平台原始 JSON，做向前兼容缓冲层。
* 不在此处声明 ``Project`` / ``Chapter`` / ``PromptTemplate`` /
  ``GenerationTask`` 上的反向 ``relationship``：避免触碰其他模型文件，符合
  W2-T2 任务"不修改其他模型文件"的边界要求；如后续需要双向导航，可在
  对应模型文件中按需补充 ``back_populates``。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin
from app.models.types import FormulaRegion, Platform, StoryVariantStatus


class StoryFormula(Base, TimestampMixin):
    """剧情公式注册表 —— 系统级故事结构模板。

    每条记录代表一种被验证过的"叙事公式"（例如 ``underdog_triumph``
    凡人逆袭、``slap_face_opening`` 开局打脸等），承载：

    * ``structure``：完整 beat 结构 JSON（含 ``beats`` 数组、
      ``total_shots``、``duration_sec_range`` 等），驱动 LLM 生成。
    * ``risk_flags``：合规风险标记（如 ``requires_yanyi_label``
      要求添加"演绎"水印），合规检查阶段读取。
    * ``psychology`` / ``use_cases`` / ``avoid_cases``：人工说明，
      用于产品端展示与运营选择。
    * ``prompt_template_id``：硬绑定一个提示词模板，ON DELETE
      RESTRICT 防止误删被引用的模板。

    ``is_system`` 默认 ``True``，标记为内置数据。仓库初始化脚本写入后，
    应用层不应允许直接删除；如确有下线需求，请通过 ``sort_order`` 隐藏
    或新增"启用/禁用"字段（不在 P1 范围）。
    """

    __tablename__ = "story_formulas"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        comment="公式 ID（如 underdog_triumph）",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="中文名称",
    )
    region: Mapped[FormulaRegion] = mapped_column(
        String(16),
        nullable=False,
        default=FormulaRegion.cn.value,
        server_default=FormulaRegion.cn.value,
        index=True,
        comment="适用地域：cn / global",
    )
    category: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="cn_viral",
        server_default="cn_viral",
        index=True,
        comment="分类标签：cn_viral / western_classic / modern_short",
    )
    structure: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="完整 beat 结构 JSON（含 beats 数组、total_shots、duration_sec_range）",
    )
    risk_flags: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="风险标记数组（如 requires_yanyi_label）",
    )
    sample_dialog: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
        comment="完整示例剧本（变量化）",
    )
    typical_duration_sec: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=60,
        server_default="60",
        comment="典型时长（秒）",
    )
    typical_shot_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=4,
        server_default="4",
        comment="典型镜头数",
    )
    psychology: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
        comment="心理学原理：为什么有效",
    )
    use_cases: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="适用场景",
    )
    avoid_cases: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="禁忌场景",
    )
    prompt_template_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("prompt_templates.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="绑定的提示词模板（ON DELETE RESTRICT）",
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
        index=True,
        comment="UI 显示排序（升序）",
    )

    __table_args__ = (
        # 前端按 region + category 联合筛选公式列表，建联合索引加速。
        Index("ix_story_formulas_region_category", "region", "category"),
    )


class StoryVariant(Base, TimestampMixin):
    """脚本变体 —— 同一项目下可有多个 A/B 测试版本。

    使用场景：
    * 在剧情带货项目中，针对同一商品/章节，基于不同公式或参数生成多版
      剧本，对比效果。
    * P1 仅支持手动创建（前端发起一次"生成变体"动作即一条记录），
      ``generated_by_task_id`` 关联触发它的 :class:`GenerationTask`。
    * P2 启用 ``hook_pattern_id`` / ``cta_pattern_id`` / ``archetype`` /
      ``is_champion``，配合钩子模式库与品牌人格系统做更精细的 A/B。

    Foreign keys：
    * ``project_id`` / ``chapter_id``：CASCADE，跟随项目/章节删除。
    * ``formula_id``：RESTRICT，公式被引用时禁止删除，保护历史变体的
      可追溯性。
    """

    __tablename__ = "story_variants"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        comment="变体唯一 ID",
    )
    project_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属项目",
    )
    chapter_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属章节",
    )
    formula_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("story_formulas.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="使用的剧情公式（ON DELETE RESTRICT）",
    )
    hook_pattern_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        default=None,
        index=True,
        comment="钩子模式 ID（P2 启用，无 FK 待 hook_patterns 表落地）",
    )
    cta_pattern_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        default=None,
        index=True,
        comment="CTA 模式 ID（P2 启用，无 FK 待 cta_patterns 表落地）",
    )
    archetype: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        default=None,
        comment="品牌人格（P2 启用 BrandArchetype 枚举，本期保留为 String）",
    )
    voice_pack_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("voice_packs.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
        index=True,
        comment="变体级主角默认音色（T17，覆盖 Character.voice_pack_id）",
    )
    narration_voice_pack_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("voice_packs.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
        index=True,
        comment="变体级旁白音色（T17，line_mode=VOICE_OVER 时使用）",
    )
    script_full_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
        comment="完整剧本文本",
    )
    script_breakdown: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="镜头分解结果 JSON",
    )
    status: Mapped[StoryVariantStatus] = mapped_column(
        String(16),
        nullable=False,
        default=StoryVariantStatus.draft.value,
        server_default=StoryVariantStatus.draft.value,
        index=True,
        comment="状态：draft / generating / ready / failed",
    )
    is_champion: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
        comment="是否冠军变体（P2 启用，A/B 决出最优后置位）",
    )
    compliance_score: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="合规评分 0-100（合规检查器写入）",
    )
    generated_by_task_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        default=None,
        index=True,
        comment="生成此变体的 GenerationTask ID（无硬 FK，便于任务清理）",
    )


class StoryOutcome(Base, TimestampMixin):
    """脚本变体的实际投放效果数据。

    P1 仅创建表保留扩展空间，避免后续上线时再做迁移；P3 启用录入与分析。

    设计要点：

    * ``plays`` 使用 :class:`~sqlalchemy.BigInteger`：爆款短视频播放量
      极易超过 ``2^31`` (~21.4 亿)，普通 ``Integer`` 会溢出。
    * ``completion_rate_3s`` / ``completion_rate_full`` 允许为空：尚未
      回传或平台不提供时保留 ``NULL``，与"取值为 0"区分。
    * ``raw_payload`` 保留平台原始 JSON，作为 schema 变化的缓冲层；
      未来字段扩展可先解析自 ``raw_payload``。
    * ``variant_id`` 上 ``CASCADE``：变体删除时联动清理效果数据。
    """

    __tablename__ = "story_outcomes"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="自增主键",
    )
    variant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("story_variants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联变体",
    )
    platform: Mapped[Platform] = mapped_column(
        String(32),
        nullable=False,
        default=Platform.douyin.value,
        server_default=Platform.douyin.value,
        index=True,
        comment="投放平台：douyin / kuaishou / xiaohongshu / youtube / tiktok",
    )
    plays: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
        comment="播放量（BigInteger，避免爆款超 2^31）",
    )
    completion_rate_3s: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        default=None,
        comment="3 秒完播率（0~1，未回传时为 NULL）",
    )
    completion_rate_full: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        default=None,
        comment="完整完播率（0~1，未回传时为 NULL）",
    )
    interactions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="互动量（点赞+评论+分享）",
    )
    cart_clicks: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="加购点击",
    )
    orders: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="订单数",
    )
    gmv: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        server_default="0",
        comment="GMV（人民币）",
    )
    notes: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
        comment="备注",
    )
    raw_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="平台原始数据 JSON（容忍未来 schema 变化）",
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="数据记录时点（业务侧统计窗口的截止时间）",
    )


__all__ = [
    "StoryFormula",
    "StoryVariant",
    "StoryOutcome",
]
