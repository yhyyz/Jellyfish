/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_HookPatternRead_ } from '../models/ApiResponse_HookPatternRead_';
import type { ApiResponse_list_HookPatternRead__ } from '../models/ApiResponse_list_HookPatternRead__';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class StudioHookPatternsService {
    /**
     * 钩子模式列表（按 pattern_type 过滤，sort_order 升序）
     * 列出所有系统级钩子模式（不分页，规模 ≤10 条）。
     * @returns ApiResponse_list_HookPatternRead__ Successful Response
     * @throws ApiError
     */
    public static listHookPatternsApiV1StudioHookPatternsGet({
        patternType,
    }: {
        /**
         * 过滤钩子类型（question / conflict / contrast / ...）
         */
        patternType?: (string | null),
    }): CancelablePromise<ApiResponse_list_HookPatternRead__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/hook-patterns',
            query: {
                'pattern_type': patternType,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 钩子模式详情
     * 按 ID 获取钩子详情，不存在返回 404。
     * @returns ApiResponse_HookPatternRead_ Successful Response
     * @throws ApiError
     */
    public static getHookPatternApiV1StudioHookPatternsPatternIdGet({
        patternId,
    }: {
        patternId: string,
    }): CancelablePromise<ApiResponse_HookPatternRead_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/hook-patterns/{pattern_id}',
            path: {
                'pattern_id': patternId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
