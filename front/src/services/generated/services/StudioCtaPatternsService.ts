/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_CtaPatternRead_ } from '../models/ApiResponse_CtaPatternRead_';
import type { ApiResponse_list_CtaPatternRead__ } from '../models/ApiResponse_list_CtaPatternRead__';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class StudioCtaPatternsService {
    /**
     * CTA 模式列表（按 hardness × urgency_type 过滤，sort_order 升序）
     * 列出所有系统级 CTA 模式（不分页，规模 ≤5 条）。
     * @returns ApiResponse_list_CtaPatternRead__ Successful Response
     * @throws ApiError
     */
    public static listCtaPatternsApiV1StudioCtaPatternsGet({
        hardness,
        urgencyType,
    }: {
        /**
         * 过滤硬度（soft / medium / hard）
         */
        hardness?: (string | null),
        /**
         * 过滤驱动类型（scarcity / urgency / social_proof / benefit / risk_removal）
         */
        urgencyType?: (string | null),
    }): CancelablePromise<ApiResponse_list_CtaPatternRead__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/cta-patterns',
            query: {
                'hardness': hardness,
                'urgency_type': urgencyType,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * CTA 模式详情
     * 按 ID 获取 CTA 详情，不存在返回 404。
     * @returns ApiResponse_CtaPatternRead_ Successful Response
     * @throws ApiError
     */
    public static getCtaPatternApiV1StudioCtaPatternsPatternIdGet({
        patternId,
    }: {
        patternId: string,
    }): CancelablePromise<ApiResponse_CtaPatternRead_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/cta-patterns/{pattern_id}',
            path: {
                'pattern_id': patternId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
