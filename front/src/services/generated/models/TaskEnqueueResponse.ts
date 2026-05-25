/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 3 个 commerce* 异步任务入口的统一响应壳。
 *
 * Attributes:
 * task_id: 新建 ``GenerationTask`` 的主键，前端用它后续轮询状态。
 * task_kind: 任务类型，用于前端区分要展示的进度/结果面板。
 * status: 入队后的初始状态，约定固定为 ``"pending"``。
 * enqueued_at: 入队时间戳；以 server-side 时间为准，便于排查
 * “前端发起 vs 实际投递”的延迟。
 */
export type TaskEnqueueResponse = {
    /**
     * 任务 ID（GenerationTask.id）
     */
    task_id: string;
    /**
     * 任务类型：product_info_extract / story_script_generate / compliance_check
     */
    task_kind: string;
    /**
     * 入队后的初始状态，固定为 'pending'
     */
    status: string;
    /**
     * 入队时间戳（server-side）
     */
    enqueued_at: string;
};

