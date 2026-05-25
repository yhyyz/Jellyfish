/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_BrandArchetypeRead_ } from '../models/ApiResponse_BrandArchetypeRead_';
import type { ApiResponse_list_BrandArchetypeRead__ } from '../models/ApiResponse_list_BrandArchetypeRead__';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class StudioBrandArchetypesService {
    /**
     * 品牌人格原型列表（sort_order 升序）
     * 列出所有系统级品牌人格原型（不分页，规模 ≤12 条）。
     * @returns ApiResponse_list_BrandArchetypeRead__ Successful Response
     * @throws ApiError
     */
    public static listBrandArchetypesApiV1StudioBrandArchetypesGet(): CancelablePromise<ApiResponse_list_BrandArchetypeRead__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/brand-archetypes',
        });
    }
    /**
     * 品牌人格原型详情
     * 按 ID 获取品牌原型详情，不存在返回 404。
     * @returns ApiResponse_BrandArchetypeRead_ Successful Response
     * @throws ApiError
     */
    public static getBrandArchetypeApiV1StudioBrandArchetypesArchetypeIdGet({
        archetypeId,
    }: {
        archetypeId: string,
    }): CancelablePromise<ApiResponse_BrandArchetypeRead_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/brand-archetypes/{archetype_id}',
            path: {
                'archetype_id': archetypeId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
