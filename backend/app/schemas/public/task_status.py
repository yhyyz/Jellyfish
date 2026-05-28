"""第三方任务状态查询响应（``GET /api/v1/public/commerce/tasks/{id}``）。

为什么独立成文件而不是复用 :class:`app.schemas.task.TaskRead`：

    内部 ``TaskRead`` 直接展开 ``GenerationTask`` 的 ``payload`` /
    ``executor_*`` / ``cancel_reason`` 等字段，那些字段对 SaaS 调用方
    既没有意义、又会暴露内部任务编排细节（哪个 worker、哪条 Celery
    队列、哪一段错误堆栈）。本 envelope 只回 4 个字段：
    ``status``、``progress``、``result_file_id``、``error``，
    让公开契约保持最小表面，避免嗅探。

为什么 ``error`` 是空串而不是 ``Optional[str]``：

    与 ORM 列定义对齐 —— ``GenerationTask.error`` 在数据库层是
    ``Text NOT NULL DEFAULT ''``，业务约定"空串 = 无错误"。直接透
    传该约定，避免在 schema 层做 ``"" -> None`` 的多余规整逻辑。

为什么 ``result_file_id`` 用 ``str | None`` 而不是结构化对象：

    第三方调用方只需要知道"产物在哪"——拿到 file id 后再去
    ``GET /api/v1/public/commerce/files/{id}`` 下载（后续 wave 落地）。
    把 result 字典摊平成业务无关的 file id 既能屏蔽内部 result
    schema 的演进，又能让前端展示统一的"下载入口"。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PublicTaskStatusRead(BaseModel):
    """``/api/v1/public/commerce/tasks/{task_id}`` 的最小响应模型。

    Attributes:
        status: 任务状态字符串（``pending`` / ``running`` /
            ``streaming`` / ``succeeded`` / ``failed`` / ``cancelled``）。
            与 :class:`app.models.task.GenerationTaskStatus` 枚举值对齐，
            但以纯字符串形式返回，避免对外暴露内部 enum 类型。
        progress: 进度百分比，取值 0–100 的整数。
        result_file_id: 仅当任务成功且产物为单文件时返回的 ``FileItem``
            主键；其它情况下为 ``None``。复杂多文件结果（章节级 av_export
            等）不在本 envelope 体现，由下游另起 endpoint 暴露。
        error: 失败原因；约定空串表示"无错误"，与 ORM
            ``GenerationTask.error`` 列契约保持一致。
    """

    model_config = ConfigDict(extra="forbid")

    status: str = Field(
        ...,
        description="任务状态：pending/running/streaming/succeeded/failed/cancelled",
    )
    progress: int = Field(..., ge=0, le=100, description="进度 0-100")
    result_file_id: str | None = Field(
        default=None,
        description="任务成功且产物为单文件时返回的 FileItem 主键，否则为 null",
    )
    error: str = Field(
        default="",
        description="失败原因；空串表示无错误（与 ORM 列契约一致）",
    )


__all__ = ["PublicTaskStatusRead"]
