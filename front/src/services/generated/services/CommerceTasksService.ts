/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_TaskEnqueueResponse_ } from '../models/ApiResponse_TaskEnqueueResponse_';
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
}
