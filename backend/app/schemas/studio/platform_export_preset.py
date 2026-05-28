"""Studio 平台导出预设 schemas（W23-T1，P4 Wave A）。

本模块对应 :class:`app.models.platform_export_preset.PlatformExportPreset`，
为 ``/api/v1/studio/platform-export-presets/*`` 一组路由提供 CRUD 入参 /
出参 DTO：

- :class:`PlatformExportPresetRead` — 列表 / 详情 / 创建 / 更新接口的
  统一响应模型；字段直接映射自 ORM 列。
- :class:`PlatformExportPresetCreate` — POST 入参；用户态创建强制
  ``is_system=False``，service 层再叠加 ``id`` 默认生成与重名校验。
- :class:`PlatformExportPresetUpdate` — PATCH 入参；全部字段可选，
  service 层 ``model_dump(exclude_unset=True)`` 实现"只改传过来的字段"。

只读语义不适用于本模块——P4 Wave A 起对用户预设开放完整 CRUD，但系统
级预设（``is_system=True``）的 DELETE 在路由层会被显式拒绝（400）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PlatformExportPresetRead(BaseModel):
    """PlatformExportPreset 通用响应。

    用于 ``GET / POST / PATCH /api/v1/studio/platform-export-presets/*``
    的成功响应数据 ``data`` 字段；字段直接映射自 ORM 列。
    """

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="预设 ID（如 douyin_default / tiktok_default）")
    name: str = Field(..., description="展示名称")
    platform: str = Field(
        ...,
        description="目标投放平台（douyin / kuaishou / xiaohongshu / youtube / tiktok）",
    )
    aspect_ratio: str = Field(..., description="画幅比例（9:16 / 1:1 / 16:9）")
    max_duration_sec: int = Field(..., description="平台允许的最大单条时长（秒）")
    subtitle_style_id: str | None = Field(
        None,
        description="可选：默认字幕样式 ID（关联 subtitle_styles.id）",
    )
    voice_pack_id: str | None = Field(
        None,
        description="可选：默认音色包 ID（关联 voice_packs.id）",
    )
    watermark_file_id: str | None = Field(
        None,
        description="可选：水印 PNG/SVG 的 FileItem ID（关联 files.id）",
    )
    sticker_specs: list[dict[str, Any]] = Field(
        default_factory=list,
        description="贴纸装配规则数组 [{type, position, asset_id}, ...]",
    )
    file_format: str = Field(..., description="导出容器格式（mp4 / mov）")
    codec_preset: str = Field(..., description="编码预设（h264_high_4_1 等）")
    loudness_lufs: float = Field(..., description="目标响度 LUFS（负值）")
    is_system: bool = Field(
        ..., description="系统级预设标记，true 时不可被业务层删除"
    )
    sort_order: int = Field(..., description="UI 列表排序权重（升序）")
    description: str = Field("", description="预设描述（运营备注）")
    created_at: datetime = Field(..., description="入库时间")
    updated_at: datetime = Field(..., description="最近一次更新时间")


class PlatformExportPresetCreate(BaseModel):
    """创建用户态预设的入参。

    系统预设由启动期 bootstrap 幂等管理，本入参不允许声明 ``is_system``
    字段（service 层强制 ``is_system=False``）。``id`` 缺省时由 service
    生成 ``uuid4().hex``；``platform`` / ``aspect_ratio`` 等关键字段强制
    填写。
    """

    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(
        None,
        description="预设 ID；缺省由 service 生成 uuid4().hex",
        max_length=64,
    )
    name: str = Field(..., description="展示名称", max_length=255)
    platform: str = Field(
        ...,
        description="目标投放平台（douyin / kuaishou / xiaohongshu / youtube / tiktok）",
    )
    aspect_ratio: str = Field(
        ...,
        description="画幅比例（9:16 / 1:1 / 16:9）",
        max_length=8,
    )
    max_duration_sec: int = Field(..., description="最大单条时长（秒）", gt=0)
    subtitle_style_id: str | None = Field(None, description="可选：默认字幕样式 ID")
    voice_pack_id: str | None = Field(None, description="可选：默认音色包 ID")
    watermark_file_id: str | None = Field(None, description="可选：水印文件 ID")
    sticker_specs: list[dict[str, Any]] = Field(
        default_factory=list,
        description="贴纸装配规则数组",
    )
    file_format: str = Field("mp4", description="容器格式", max_length=16)
    codec_preset: str = Field(
        "h264_high_4_1", description="编码预设", max_length=32
    )
    loudness_lufs: float = Field(-16.0, description="目标响度 LUFS")
    sort_order: int = Field(0, description="排序权重")
    description: str = Field("", description="预设描述")


class PlatformExportPresetUpdate(BaseModel):
    """更新预设的入参（PATCH 语义）。

    全部字段可选，service 层用 ``model_dump(exclude_unset=True)`` 实现
    "只改传过来的字段"。``is_system`` 不开放修改（系统预设保持系统态）。
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, max_length=255)
    platform: str | None = None
    aspect_ratio: str | None = Field(None, max_length=8)
    max_duration_sec: int | None = Field(None, gt=0)
    subtitle_style_id: str | None = None
    voice_pack_id: str | None = None
    watermark_file_id: str | None = None
    sticker_specs: list[dict[str, Any]] | None = None
    file_format: str | None = Field(None, max_length=16)
    codec_preset: str | None = Field(None, max_length=32)
    loudness_lufs: float | None = None
    sort_order: int | None = None
    description: str | None = None


__all__ = [
    "PlatformExportPresetRead",
    "PlatformExportPresetCreate",
    "PlatformExportPresetUpdate",
]
