"""品牌人格原型（BrandArchetype）模型 —— W11-T2，P2 启用前的注册表。

本文件提供一张系统级"品牌人格原型"注册表 :class:`BrandArchetype`，承载
12 个与 tonethief 词汇表对齐的人格原型：``sage`` / ``jester`` / ``rebel``
/ ``provocateur`` / ``maverick`` / ``friend`` / ``expert`` /
``cheerleader`` / ``storyteller`` / ``analyst`` / ``coach`` /
``minimalist``。

与 :class:`app.models.types.BrandArchetype` 枚举的协作：

* 表行的 ``id`` 字段同时充当 ``BrandArchetype`` 枚举值（``sage`` /
  ``jester`` / ...），使 ``commerce_story_configs.archetype`` /
  ``StoryVariant.archetype`` 字段能直接拿 ``id`` 当业务 key；
* 这一约定由 :func:`bootstrap_builtin_brand_archetypes` 在启动期对齐：内
  置 12 条 ``id`` 与枚举值一一对应。

设计要点：

* ``voice_traits``、``speech_patterns``、``sample_brands`` 三列均使用
  JSON：原型卡片在前端按品牌识别度展示（do/don't、代表品牌等），落库时
  保留结构化语义而非把所有信息塞进单段长文本；
* ``motivation`` 是 80-150 字的"核心动机"叙述，回答"这个原型为什么存
  在/它解决什么品牌沟通问题"，是 LLM 改写阶段的关键输入；
* 与 :class:`HookPattern` / :class:`CtaPattern` 共享 ``is_system`` /
  ``sort_order`` 约定，启动期由 bootstrap 幂等同步。
"""

from __future__ import annotations

from typing import Any

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


class BrandArchetype(Base, TimestampMixin):
    """品牌人格原型注册表 —— 12 个 archetype，与 tonethief 词汇表对齐。

    P2 阶段的 ``ArchetypeVoiceRewriterAgent`` 会读取本表的
    ``motivation`` / ``voice_traits`` / ``speech_patterns`` 输出到 LLM 系
    统消息，把通用脚本改写成符合品牌人格的风格。

    ``id`` 字段必须与 :class:`app.models.types.BrandArchetype` 枚举值保
    持一致，作为跨表/跨服务的稳定 business key。
    """

    __tablename__ = "brand_archetypes"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        comment="原型 ID（与 BrandArchetype 枚举值同名，如 sage / jester）",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="英文名称（Sage / Jester / ...）",
    )
    name_zh: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="中文名称（智者 / 小丑 / ...）",
    )
    motivation: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
        comment="核心动机（why this archetype exists，~80-150 字）",
    )
    voice_traits: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="语调描述符列表（5-10 个形容词）",
    )
    speech_patterns: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="语言模式 JSON：{do: [...], dont: [...]}",
    )
    sample_brands: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="代表品牌列表（3-5 个真实品牌）",
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
        comment="系统原型，不可删除",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        index=True,
        comment="UI 显示排序（升序）",
    )


__all__ = ["BrandArchetype"]
