"""钩子模式（HookPattern）模型 —— W11-T2，P2 启用前的注册表。

本文件提供一张系统级"钩子模式"注册表 :class:`HookPattern`，用于管理 P2
阶段会启用的 10 种短视频开场钩子（``question_hook`` / ``conflict_hook``
/ ``contrast_hook`` / ``numerical_hook`` / ``curiosity_hook`` /
``shock_hook`` / ``relatable_hook`` / ``dialogue_hook`` /
``visual_hook`` / ``pov_hook``）。

设计要点：

* 与 :mod:`app.models.story_formula` 中 ``StoryFormula`` 同构：均为系统级
  "运营/产品资产"注册表，``is_system=True`` 表示由内置 bootstrap 写入；
* 不在本期为 ``StoryVariant.hook_pattern_id`` 增加硬外键 —— 钩子模式与剧
  情公式属于不同 P2 子系统，硬绑定时机留给 W13/W14 钩子集成阶段；
* JSON 列 ``use_cases`` / ``avoid_cases`` 服务于产品端 UI 展示（"什么时
  候用"/"什么时候不用"），同时用于运营文档同步；
* ``template_text`` 是 Jinja2 模板片段，由 LLM workflow 拼装到生成提示词
  中，避免每次生成都把全部模板硬塞进系统消息。
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


class HookPattern(Base, TimestampMixin):
    """钩子模式注册表 —— P2 启用，10 个内置钩子（question/conflict/...）。

    每条记录对应一种"开场抓人"的钩子模板，被 P2 钩子工作流（Wave 13/14）
    在生成开场镜头时检索使用。``pattern_type`` 决定钩子类型，
    ``template_text`` 是落地到 LLM 提示词的 Jinja2 片段，
    ``use_cases`` / ``avoid_cases`` 作为运营层的"选钩子"指南。

    系统模板 (``is_system=True``) 由 :func:`bootstrap_builtin_hook_patterns`
    幂等写入；应用层不应允许直接删除，确需下线请通过 ``sort_order`` 排序
    隐藏，或后续新增"启用/禁用"字段。
    """

    __tablename__ = "hook_patterns"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        comment="钩子 ID（如 question_hook）",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="中文名称（如 问句钩子）",
    )
    pattern_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        comment="钩子类型：question / conflict / contrast / ...",
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
        comment="钩子说明（运营/UI 展示，~80-150 字）",
    )
    template_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
        comment="Jinja2 模板片段（LLM 渲染开场用）",
    )
    psychology: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
        comment="心理学原理：为什么这种钩子有效",
    )
    use_cases: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="适用场景列表",
    )
    avoid_cases: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="禁忌场景列表",
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


__all__ = ["HookPattern"]
