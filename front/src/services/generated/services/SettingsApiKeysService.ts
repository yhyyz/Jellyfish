/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiKeyCreateRequest } from '../models/ApiKeyCreateRequest';
import type { ApiKeyHashRequest } from '../models/ApiKeyHashRequest';
import type { ApiResponse_ApiKeyCreated_ } from '../models/ApiResponse_ApiKeyCreated_';
import type { ApiResponse_ApiKeyRead_ } from '../models/ApiResponse_ApiKeyRead_';
import type { ApiResponse_ApiKeyUsageRead_ } from '../models/ApiResponse_ApiKeyUsageRead_';
import type { ApiResponse_list_ApiKeyRead__ } from '../models/ApiResponse_list_ApiKeyRead__';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class SettingsApiKeysService {
    /**
     * 创建 API key（plaintext 仅本次返回）
     * 创建一条新的 ``ApiKeyQuota`` 行。
     *
     * 返回的 ``data.plaintext_key`` 是 SaaS 调用方今后唯一可见的明文，
     * 后端不存储——丢失后只能创建新的 key。
     * @returns ApiResponse_ApiKeyCreated_ Successful Response
     * @throws ApiError
     */
    public static createApiKeyEndpointApiV1SettingsApiKeysPost({
        requestBody,
    }: {
        requestBody: ApiKeyCreateRequest,
    }): CancelablePromise<ApiResponse_ApiKeyCreated_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/settings/api-keys',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 列出 API key（默认排除已 revoke）
     * 列出所有 API key。
     *
     * 路由层保持瘦身：直接 ``model_validate`` 委托给
     * :class:`ApiKeyRead`，永不返回明文字段。
     * @returns ApiResponse_list_ApiKeyRead__ Successful Response
     * @throws ApiError
     */
    public static listApiKeysEndpointApiV1SettingsApiKeysGet({
        includeInactive = false,
    }: {
        /**
         * 是否包含已 revoke 的 inactive 行；缺省仅列活跃 key
         */
        includeInactive?: boolean,
    }): CancelablePromise<ApiResponse_list_ApiKeyRead__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/settings/api-keys',
            query: {
                'include_inactive': includeInactive,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Revoke API key（软删，保留历史计数）
     * 将指定 key 标记为 ``is_active=False``。
     *
     * 若 hash 不存在返回 404；重复 revoke 同一 key 幂等成功。
     * @returns ApiResponse_ApiKeyRead_ Successful Response
     * @throws ApiError
     */
    public static revokeApiKeyEndpointApiV1SettingsApiKeysRevokePost({
        requestBody,
    }: {
        requestBody: ApiKeyHashRequest,
    }): CancelablePromise<ApiResponse_ApiKeyRead_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/settings/api-keys/revoke',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 查询单条 API key 的配额计数
     * 返回单条 key 的实时 ``consumed_today`` / ``consumed_this_month``。
     *
     * 允许查询已 revoke 的 key（用于事后审计）；前端管理面板根据
     * ``is_active`` 决定是否给出告警。
     * @returns ApiResponse_ApiKeyUsageRead_ Successful Response
     * @throws ApiError
     */
    public static getApiKeyUsageEndpointApiV1SettingsApiKeysUsagePost({
        requestBody,
    }: {
        requestBody: ApiKeyHashRequest,
    }): CancelablePromise<ApiResponse_ApiKeyUsageRead_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/settings/api-keys/usage',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
