/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_TaskEnqueueResponse_ } from '../models/ApiResponse_TaskEnqueueResponse_';
import type { BatchGenerationRequest } from '../models/BatchGenerationRequest';
import type { ComplianceCheckRequest } from '../models/ComplianceCheckRequest';
import type { ProductExtractRequest } from '../models/ProductExtractRequest';
import type { ScriptGenerateRequest } from '../models/ScriptGenerateRequest';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class CommerceTasksService {
    /**
     * 入队：商品信息抽取（异步任务）
     * 收参 → 落 ``GenerationTask`` 行 → Celery 投递 → 返回 task_id。
     * @returns ApiResponse_TaskEnqueueResponse_ Successful Response
     * @throws ApiError
     */
    public static enqueueProductExtractApiV1CommerceProductsExtractPost({
        requestBody,
    }: {
        requestBody: ProductExtractRequest,
    }): CancelablePromise<ApiResponse_TaskEnqueueResponse_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/commerce/products/extract',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 入队：剧情脚本生成（异步任务）
     * 收参 → 落 ``GenerationTask`` 行 → Celery 投递 → 返回 task_id。
     * @returns ApiResponse_TaskEnqueueResponse_ Successful Response
     * @throws ApiError
     */
    public static enqueueScriptGenerateApiV1CommerceScriptGeneratePost({
        requestBody,
    }: {
        requestBody: ScriptGenerateRequest,
    }): CancelablePromise<ApiResponse_TaskEnqueueResponse_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/commerce/script-generate',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 入队：合规检查（异步任务）
     * 收参 → 落 ``GenerationTask`` 行 → Celery 投递 → 返回 task_id。
     * @returns ApiResponse_TaskEnqueueResponse_ Successful Response
     * @throws ApiError
     */
    public static enqueueComplianceCheckApiV1CommerceComplianceCheckPost({
        requestBody,
    }: {
        requestBody: ComplianceCheckRequest,
    }): CancelablePromise<ApiResponse_TaskEnqueueResponse_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/commerce/compliance/check',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 批量生成：一次性入队 N 个 story_script_generate 子任务
     * 批量生成入口：把变体网格作为一次性请求落到 ``slow`` 队列上。
     *
     * 路由职责仍保持瘦身：仅做 Pydantic 校验 + 调 service + 包响应壳；
     * “一行变体 -> 一个子 ``story_script_generate`` 任务”的真正编排逻辑
     * 在 :func:`app.services.commerce.story_video_batch_generate_worker.run_story_video_batch_generate_task`
     * 里执行，由 worker 在异步链路上完成。
     * @returns ApiResponse_TaskEnqueueResponse_ Successful Response
     * @throws ApiError
     */
    public static enqueueStoryBatchApiV1CommerceStoryBatchesPost({
        requestBody,
    }: {
        requestBody: BatchGenerationRequest,
    }): CancelablePromise<ApiResponse_TaskEnqueueResponse_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/commerce/story-batches',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
