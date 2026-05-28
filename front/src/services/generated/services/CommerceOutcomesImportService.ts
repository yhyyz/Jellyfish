/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_ImportSummary_ } from '../models/ApiResponse_ImportSummary_';
import type { Body_import_outcomes_csv_api_v1_commerce_outcomes_import_post } from '../models/Body_import_outcomes_csv_api_v1_commerce_outcomes_import_post';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class CommerceOutcomesImportService {
    /**
     * 批量导入投放效果 CSV（5MB 上限，单行失败不中断）
     * 以 multipart 接收 CSV，按 mapping profile 流式导入。
     *
     * Args:
     * request: 用于读取 ``Content-Length`` 做前置 5MB 校验。
     * file: 上传的 CSV 文件；UTF-8 编码（兼容 BOM）。
     * mapping_profile: ``douyin`` / ``xiaohongshu`` / ``default``，
     * 未知值回退 ``default``。
     * db: 由 ``get_db`` 注入的异步会话。
     *
     * Returns:
     * ``ApiResponse[ImportSummary]``。即便有失败行也返回 200，让前端
     * 能拿到 ``inserted`` / ``failed`` / ``errors`` 三段信息。
     *
     * Raises:
     * HTTPException: 413 当文件超过 5MB；400 当文件名后缀不是 csv。
     * @returns ApiResponse_ImportSummary_ Successful Response
     * @throws ApiError
     */
    public static importOutcomesCsvApiV1CommerceOutcomesImportPost({
        formData,
    }: {
        formData: Body_import_outcomes_csv_api_v1_commerce_outcomes_import_post,
    }): CancelablePromise<ApiResponse_ImportSummary_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/commerce/outcomes/import',
            formData: formData,
            mediaType: 'multipart/form-data',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
