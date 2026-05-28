/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * ``/api/v1/public/commerce/tasks/{task_id}`` 的最小响应模型。
 *
 * Attributes:
 * status: 任务状态字符串（``pending`` / ``running`` /
 * ``streaming`` / ``succeeded`` / ``failed`` / ``cancelled``）。
 * 与 :class:`app.models.task.GenerationTaskStatus` 枚举值对齐，
 * 但以纯字符串形式返回，避免对外暴露内部 enum 类型。
 * progress: 进度百分比，取值 0–100 的整数。
 * result_file_id: 仅当任务成功且产物为单文件时返回的 ``FileItem``
 * 主键；其它情况下为 ``None``。复杂多文件结果（章节级 av_export
 * 等）不在本 envelope 体现，由下游另起 endpoint 暴露。
 * error: 失败原因；约定空串表示"无错误"，与 ORM
 * ``GenerationTask.error`` 列契约保持一致。
 */
export type PublicTaskStatusRead = {
    /**
     * 任务状态：pending/running/streaming/succeeded/failed/cancelled
     */
    status: string;
    /**
     * 进度 0-100
     */
    progress: number;
    /**
     * 任务成功且产物为单文件时返回的 FileItem 主键，否则为 null
     */
    result_file_id?: (string | null);
    /**
     * 失败原因；空串表示无错误（与 ORM 列契约一致）
     */
    error?: string;
};

