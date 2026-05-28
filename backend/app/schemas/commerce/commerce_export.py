"""``/api/v1/commerce/export`` 请求/响应 schema（W23-T2，P4 Wave B）。

为什么单独成文件
----------------

P4 Wave B 起 commerce/* 多了一条"平台导出"链路：把已落地的章节成片
按 :class:`PlatformExportPreset` 转换为不同平台的发布版本。它与既有
``commerce/tasks`` 模块下 8 个异步任务入口职责并列但语义独立——
导出不依赖 LLM、不修改业务实体，只做"多版本 mp4 衍生"，所以拆出
独立 schema 文件以避免 ``tasks.py`` 持续膨胀。

设计要点
--------

- ``extra="forbid"``：与 ``commerce/tasks`` 系列保持一致，前端拼写错误
  / 多余字段在联调期就能拿到 422 反馈。
- 仅 2 个必填字段：``variant_id`` + ``preset_id``。worker 端会按 variant
  反查 chapter_av_export 产物 + 按 preset 装配 ffmpeg 命令；其它参数都
  来自预设行本身（aspect / codec / loudnorm / 水印 / 贴纸）。
- 不在 schema 层校验 ``variant_id`` / ``preset_id`` 是否存在：worker 内
  做存在性校验更贴近"业务事实"（同时 schema 层做 DB 校验会让 422 与
  404 语义混淆）。

响应壳沿用 :class:`app.schemas.commerce.tasks.TaskEnqueueResponse`，与
其它 commerce/* 入队入口对齐，前端只需共享一份轮询逻辑。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CommerceExportRequest(BaseModel):
    """``POST /api/v1/commerce/export`` 请求体。

    Attributes:
        variant_id: 目标 :class:`StoryVariant` ID；worker 据此回查关联章节
            的 chapter_av_export 产物 mp4。
        preset_id: 目标 :class:`PlatformExportPreset` ID（如
            ``douyin_default`` / ``tiktok_default``），worker 据此装配
            ffmpeg 转换参数。
    """

    model_config = ConfigDict(extra="forbid")

    variant_id: str = Field(
        ...,
        min_length=1,
        description="目标 StoryVariant ID（commerce 视频变体主键）",
    )
    preset_id: str = Field(
        ...,
        min_length=1,
        description=(
            "目标 PlatformExportPreset ID（如 douyin_default / "
            "tiktok_default / xiaohongshu_default 等）"
        ),
    )


__all__ = ["CommerceExportRequest"]
