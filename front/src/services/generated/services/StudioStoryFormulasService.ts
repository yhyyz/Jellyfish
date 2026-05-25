/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_list_StoryFormulaRead__ } from '../models/ApiResponse_list_StoryFormulaRead__';
import type { ApiResponse_StoryFormulaRead_ } from '../models/ApiResponse_StoryFormulaRead_';
import type { FormulaRegion } from '../models/FormulaRegion';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class StudioStoryFormulasService {
    /**
     * 剧情公式列表（按 region / category 过滤，sort_order 升序）
     * 列出所有系统级剧情公式（不分页，规模 ≤10 条）。
     * @returns ApiResponse_list_StoryFormulaRead__ Successful Response
     * @throws ApiError
     */
    public static listStoryFormulasApiV1StudioStoryFormulasGet({
        region,
        category,
    }: {
        /**
         * 过滤地域 cn / global
         */
        region?: (FormulaRegion | null),
        /**
         * 过滤分类（如 cn_workplace）
         */
        category?: (string | null),
    }): CancelablePromise<ApiResponse_list_StoryFormulaRead__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/story-formulas',
            query: {
                'region': region,
                'category': category,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 剧情公式详情
     * 按 ID 获取公式详情，不存在返回 404。
     * @returns ApiResponse_StoryFormulaRead_ Successful Response
     * @throws ApiError
     */
    public static getStoryFormulaApiV1StudioStoryFormulasFormulaIdGet({
        formulaId,
    }: {
        formulaId: string,
    }): CancelablePromise<ApiResponse_StoryFormulaRead_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/story-formulas/{formula_id}',
            path: {
                'formula_id': formulaId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
