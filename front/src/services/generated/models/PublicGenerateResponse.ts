/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * ``POST /api/v1/public/commerce/generate`` 的响应壳。
 *
 * Attributes:
 * task_id: 入队后落到 :class:`app.models.task.GenerationTask` 的主键，
 * 调用方用它去 ``GET /api/v1/public/commerce/tasks/{id}`` 拉状态。
 * status: 入队后的初始状态，固定 ``"queued"``；与内部
 * :class:`app.schemas.commerce.tasks.TaskEnqueueResponse` 的
 * ``"pending"`` 区分——对外语义统一为"队列已收下"，避免暴露
 * 内部 ``GenerationTaskStatus`` 枚举字面值。
 * estimated_eta_sec: 预估完成时间（秒），基于
 * ``variant_count × 60`` 估算；仅作前端轮询超时兜底参考，真实
 * 完成时间以任务状态机为准。
 *
 * 设计注释：
 *
 * - 不暴露 ``task_kind`` / ``enqueued_at`` / ``queue`` 等内部字段，与
 * :class:`app.schemas.public.task_status.PublicTaskStatusRead` 的
 * "最小表面"原则保持一致；
 * - ``model_config = ConfigDict(extra="forbid")`` 防止后续 wave 误把
 * 内部字段透传上来。
 */
export type PublicGenerateResponse = {
    /**
     * 任务 ID（GenerationTask.id，hex 形式）
     */
    task_id: string;
    /**
     * 入队后的初始状态，固定为 'queued'
     */
    status?: string;
    /**
     * 预估完成时间（秒）；基于 variant_count × 60 估算
     */
    estimated_eta_sec: number;
};

