/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_ComplianceProfileRead_ } from '../models/ApiResponse_ComplianceProfileRead_';
import type { ApiResponse_list_ComplianceFindingRead__ } from '../models/ApiResponse_list_ComplianceFindingRead__';
import type { ApiResponse_list_ComplianceProfileRead__ } from '../models/ApiResponse_list_ComplianceProfileRead__';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class StudioComplianceService {
    /**
     * 列出合规规则集（可按 region 过滤）
     * 列出合规规则集。
     * @returns ApiResponse_list_ComplianceProfileRead__ Successful Response
     * @throws ApiError
     */
    public static listComplianceProfilesApiV1StudioComplianceProfilesGet({
        region,
    }: {
        /**
         * 过滤地域：cn_mainland / hk_tw / overseas
         */
        region?: (string | null),
    }): CancelablePromise<ApiResponse_list_ComplianceProfileRead__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/compliance/profiles',
            query: {
                'region': region,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 取单个合规规则集详情
     * 取单个合规规则集详情，未命中返回 404。
     * @returns ApiResponse_ComplianceProfileRead_ Successful Response
     * @throws ApiError
     */
    public static getComplianceProfileApiV1StudioComplianceProfilesProfileIdGet({
        profileId,
    }: {
        profileId: string,
    }): CancelablePromise<ApiResponse_ComplianceProfileRead_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/compliance/profiles/{profile_id}',
            path: {
                'profile_id': profileId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 列出某变体的合规 finding（可按严重度/解决态过滤）
     * 列出某变体的合规 finding。
     * @returns ApiResponse_list_ComplianceFindingRead__ Successful Response
     * @throws ApiError
     */
    public static listComplianceFindingsApiV1StudioComplianceFindingsGet({
        variantId,
        severity,
        isResolved,
    }: {
        /**
         * 所属变体 ID（必填）
         */
        variantId: string,
        /**
         * 过滤严重度：info / warning / blocker
         */
        severity?: (string | null),
        /**
         * 过滤解决态：true 已解决 / false 未解决
         */
        isResolved?: (boolean | null),
    }): CancelablePromise<ApiResponse_list_ComplianceFindingRead__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/compliance/findings',
            query: {
                'variant_id': variantId,
                'severity': severity,
                'is_resolved': isResolved,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
