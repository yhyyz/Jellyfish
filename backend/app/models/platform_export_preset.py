"""平台导出预设 ORM 模型（P4 Wave A，W23-T1 引入）。

为什么存在：
    P4 阶段引入"多平台导出"能力：同一份成片需要按抖音 / 快手 / 小红书 /
    YouTube Shorts / TikTok 等不同平台输出差异化的画幅、时长、字幕样式、
    水印、贴纸与编码参数。这些差异化参数与商品 / 项目本身无关，是稳定的
    平台级别"模板"，应集中沉淀到一张配置表，避免在 chapter_av_export 链
    路里硬编码 if-else。

设计要点：
    - 表名：``platform_export_presets``，按主键 ``id``（如
      ``douyin_default`` / ``tiktok_default``）寻址，与 P3 内置 seed
      （voice_packs / subtitle_styles）一致。
    - ``is_system=True`` 的 5 条系统预设由启动期
      :func:`app.services.commerce.bootstrap_export_presets.bootstrap_platform_export_presets`
      幂等 seed；用户也可在此基础上派生 ``is_system=False`` 的自定义预设。
    - 外键全部使用 ``ON DELETE SET NULL`` 软关联：上游字幕样式 /
      音色包 / 水印文件被删除时不应级联清空预设行，业务层再处理空值
      回退即可。
    - ``sticker_specs`` 用 JSON 列承载 ``[{type, position, asset_id}, ...]``
      可变结构；P4 Wave A 不约束 schema，留给 W23-T2 渲染管线消费时
      再约束。
    - 字段命名遵循 P3 W17/W18 的"snake_case + 语义后缀"约定，便于
      生成 OpenAPI schema 与前端 generated types 平滑对齐。

字段语义见 :class:`PlatformExportPreset` 类内 ``comment``。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
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
from app.models.types import Platform


class PlatformExportPreset(Base, TimestampMixin):
    """单个"平台导出预设"行。

    覆盖一组 (画幅 + 时长 + 字幕 + 配音 + 水印 + 贴纸 + 编码 + 响度) 参数，
    在 P4 Wave A 仅作为元数据落地；W23-T2 起 chapter_av_export 路径会按
    本表 ``id`` 选取参数装配 ffmpeg 命令。

    覆盖范围：
        - 画幅：``aspect_ratio``（9:16 竖屏 / 1:1 方屏 / 16:9 横屏）。
        - 时长：``max_duration_sec``（平台允许的发布上限秒数；超过需切版）。
        - 字幕：可选关联系统级 :class:`SubtitleStyle`（``subtitle_style_id``）。
        - 配音：可选关联系统级 :class:`VoicePack`（``voice_pack_id``）。
        - 水印：可选关联用户上传的 :class:`FileItem`（``watermark_file_id``）。
        - 贴纸：``sticker_specs`` JSON 数组，元素结构由渲染管线约束。
        - 编码：``file_format`` (mp4 / mov) + ``codec_preset``
          (h264_high_4_1 / hevc_main_10 等)。
        - 响度：``loudness_lufs``（目标 LUFS，负值，平台默认 -16 LUFS）。

    系统级预设（``is_system=True``）由 bootstrap 幂等管理，业务层 DELETE
    必须返回 400 拒绝；用户派生预设（``is_system=False``）走完整 CRUD。
    """

    __tablename__ = "platform_export_presets"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        comment="预设 ID（如 douyin_default / kuaishou_default / tiktok_default）",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="展示名称（如 抖音默认 / TikTok 默认 / 小红书方屏）",
    )
    platform: Mapped[Platform] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        comment="目标投放平台（douyin / kuaishou / xiaohongshu / youtube / tiktok）",
    )
    aspect_ratio: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default="9:16",
        server_default="9:16",
        comment="画幅比例（9:16 / 1:1 / 16:9）",
    )
    max_duration_sec: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=60,
        server_default="60",
        comment="平台允许的最大单条时长，单位秒",
    )
    subtitle_style_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey(
            "subtitle_styles.id",
            name="fk_platform_export_presets_subtitle_style_id",
            ondelete="SET NULL",
        ),
        nullable=True,
        default=None,
        index=True,
        comment="可选：默认字幕样式 ID（关联 subtitle_styles.id）",
    )
    voice_pack_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey(
            "voice_packs.id",
            name="fk_platform_export_presets_voice_pack_id",
            ondelete="SET NULL",
        ),
        nullable=True,
        default=None,
        index=True,
        comment="可选：默认音色包 ID（关联 voice_packs.id）",
    )
    watermark_file_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey(
            "files.id",
            name="fk_platform_export_presets_watermark_file_id",
            ondelete="SET NULL",
        ),
        nullable=True,
        default=None,
        index=True,
        comment="可选：水印 PNG/SVG 的 FileItem ID（关联 files.id）",
    )
    sticker_specs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="贴纸装配规则数组 [{type, position, asset_id}, ...]，结构由渲染管线消费",
    )
    file_format: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="mp4",
        server_default="mp4",
        comment="导出容器格式（mp4 / mov）",
    )
    codec_preset: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="h264_high_4_1",
        server_default="h264_high_4_1",
        comment="编码预设（h264_high_4_1 / hevc_main_10 等）",
    )
    loudness_lufs: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=-16.0,
        server_default="-16.0",
        comment="目标响度 LUFS（负值，平台默认 -16 LUFS）",
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
        comment="系统级预设标记，true 时不可被业务层删除（系统 seed）",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="UI 列表排序权重（升序）",
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
        comment="预设描述（适用平台、节奏、风格等运营备注）",
    )

    __table_args__ = (
        Index(
            "ix_platform_export_presets_platform_aspect",
            "platform",
            "aspect_ratio",
        ),
    )


__all__ = ["PlatformExportPreset"]
