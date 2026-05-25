/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { BatchVariantSpec } from './BatchVariantSpec';
/**
 * 批量生成请求 —— 一次性产出 N 个变体（参数网格扫描）。
 *
 * 存在原因：
 * 与 :class:`ScriptGenerateRequest` 不同，本请求承载“一次扫描多个
 * 参数变体”的批量编排语义。把项目锚点（``project_id`` /
 * ``chapter_id``）、共享的产品/受众/平台/时长，以及变体网格
 * （``variants``）放在一起，作为 ``story_video_batch_generate``
 * worker 的入参契约。
 *
 * 设计要点：
 * - ``model_config = ConfigDict(extra="forbid")``：与既有 commerce
 * 请求体保持一致，避免上游误传字段被静默吞掉；
 * - ``target_duration_sec`` 的 ``ge=15, le=180`` 与
 * :class:`StoryGenerationVars` / ``ScriptGenerateRequest`` 对齐，
 * 避免变体级时长漂移到无意义区间；
 * - ``variants`` 长度上限 10，下限 1：plan 给批量任务定的硬约束，
 * 避免一次性扫到几十个变体把队列撑爆；
 * - ``parallelism`` 仅作为编排提示，实际并发受 Celery worker 队列
 * 并发限制约束，本字段保留以便未来下放给调度器使用。
 *
 * Attributes:
 * project_id: 所属项目 ID。
 * chapter_id: 所属章节 ID。
 * product: 商品快照 JSON（worker 不再回查 DB）。
 * audience: 受众画像 JSON。
 * target_duration_sec: 目标视频时长（秒），15 ≤ x ≤ 180。
 * platform: 目标投放平台，默认 ``douyin``。
 * variants: 变体规格列表，长度区间 [1, 10]。
 * parallelism: 期望的并发上限（1..4），默认 2；实际并发以队列
 * 消费者为准。
 */
export type BatchGenerationRequest = {
    /**
     * 所属项目 ID
     */
    project_id: string;
    /**
     * 所属章节 ID
     */
    chapter_id: string;
    /**
     * 商品快照 JSON
     */
    product: Record<string, any>;
    /**
     * 受众画像 JSON
     */
    audience: Record<string, any>;
    /**
     * 目标视频时长（秒），约束在 15-180 之间
     */
    target_duration_sec: number;
    /**
     * 目标投放平台，默认 douyin
     */
    platform?: string;
    /**
     * 变体规格列表，长度区间 [1, 10]
     */
    variants: Array<BatchVariantSpec>;
    /**
     * 期望并发上限（1..4），实际并发以 Celery 队列消费者为准
     */
    parallelism?: number;
};

