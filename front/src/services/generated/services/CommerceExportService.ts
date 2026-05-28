/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_TaskEnqueueResponse_ } from '../models/ApiResponse_TaskEnqueueResponse_';
import type { CommerceExportRequest } from '../models/CommerceExportRequest';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class CommerceExportService {
    /**
     * 入队：平台导出（按 PlatformExportPreset 转换章节成片，P4 W23）
     * 收参 → 落 ``GenerationTask`` 行 → commit → Celery slow 队列投递 → 返回 task_id。
     *
     * 触发 ``commerce_export`` worker：把章节成片（``chapter_master_dubbed``）
     * 按 :class:`PlatformExportPreset` 转换成平台衍生版本（aspect scale+pad +
     * 水印 / 贴纸 overlay + loudnorm + 编码与容器切换），输出 :class:`FileItem`
     * 的 ``usage_kind`` 标 ``product_export``。
     * @returns ApiResponse_TaskEnqueueResponse_ Successful Response
     * @throws ApiError
     */
    public static enqueueCommerceExportApiV1CommerceExportPost({
        requestBody,
    }: {
        requestBody: CommerceExportRequest,
    }): CancelablePromise<ApiResponse_TaskEnqueueResponse_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/commerce/export',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
