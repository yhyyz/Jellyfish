/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_list_StoryOutcomeRead__ } from '../models/ApiResponse_list_StoryOutcomeRead__';
import type { ApiResponse_NoneType_ } from '../models/ApiResponse_NoneType_';
import type { ApiResponse_StoryOutcomeRead_ } from '../models/ApiResponse_StoryOutcomeRead_';
import type { StoryOutcomeCreate } from '../models/StoryOutcomeCreate';
import type { StoryOutcomeUpdate } from '../models/StoryOutcomeUpdate';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class CommerceOutcomesService {
    /**
     * 变体投放效果列表（按 recorded_at desc 排序）
     * 列出某个变体下的全部投放效果记录。
     * @returns ApiResponse_list_StoryOutcomeRead__ Successful Response
     * @throws ApiError
     */
    public static listOutcomesByVariantApiV1CommerceVariantsVariantIdOutcomesGet({
        variantId,
    }: {
        variantId: string,
    }): CancelablePromise<ApiResponse_list_StoryOutcomeRead__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/commerce/variants/{variant_id}/outcomes',
            path: {
                'variant_id': variantId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 手动录入一条投放效果
     * 创建一条 outcome 记录。
     *
     * 校验细节由 service 层兜底（``gmv >= 0`` / ``completion_rate ∈
     * [0, 1]`` / ``recorded_at <= now``）。
     * @returns ApiResponse_StoryOutcomeRead_ Successful Response
     * @throws ApiError
     */
    public static createOutcomeApiV1CommerceOutcomesPost({
        requestBody,
    }: {
        requestBody: StoryOutcomeCreate,
    }): CancelablePromise<ApiResponse_StoryOutcomeRead_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/commerce/outcomes',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 部分更新一条投放效果
     * 部分更新；仅显式传入字段会被覆盖。
     * @returns ApiResponse_StoryOutcomeRead_ Successful Response
     * @throws ApiError
     */
    public static patchOutcomeApiV1CommerceOutcomesOutcomeIdPatch({
        outcomeId,
        requestBody,
    }: {
        outcomeId: number,
        requestBody: StoryOutcomeUpdate,
    }): CancelablePromise<ApiResponse_StoryOutcomeRead_> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/commerce/outcomes/{outcome_id}',
            path: {
                'outcome_id': outcomeId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 删除一条投放效果
     * 删除单条 outcome；记录不存在时返回 404。
     * @returns ApiResponse_NoneType_ Successful Response
     * @throws ApiError
     */
    public static deleteOutcomeApiV1CommerceOutcomesOutcomeIdDelete({
        outcomeId,
    }: {
        outcomeId: number,
    }): CancelablePromise<ApiResponse_NoneType_> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/commerce/outcomes/{outcome_id}',
            path: {
                'outcome_id': outcomeId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
