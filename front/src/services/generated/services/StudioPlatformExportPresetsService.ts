/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_list_PlatformExportPresetRead__ } from '../models/ApiResponse_list_PlatformExportPresetRead__';
import type { ApiResponse_PlatformExportPresetRead_ } from '../models/ApiResponse_PlatformExportPresetRead_';
import type { PlatformExportPresetCreate } from '../models/PlatformExportPresetCreate';
import type { PlatformExportPresetUpdate } from '../models/PlatformExportPresetUpdate';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class StudioPlatformExportPresetsService {
    /**
     * 平台导出预设列表（按 platform / is_system 过滤）
     * 列出预设。
     *
     * 路由职责保持瘦身：收参 → 调 service → ``model_validate`` →
     * ``success_response``，不在此处做业务过滤或字段映射。
     * @returns ApiResponse_list_PlatformExportPresetRead__ Successful Response
     * @throws ApiError
     */
    public static listPlatformExportPresetsEndpointApiV1StudioPlatformExportPresetsGet({
        platform,
        isSystem,
    }: {
        /**
         * 按平台过滤（douyin / kuaishou / xiaohongshu / youtube / tiktok）
         */
        platform?: (string | null),
        /**
         * 是否只列系统级预设；true=仅系统 / false=仅用户自定义 / 缺省=全部
         */
        isSystem?: (boolean | null),
    }): CancelablePromise<ApiResponse_list_PlatformExportPresetRead__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/platform-export-presets',
            query: {
                'platform': platform,
                'is_system': isSystem,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 创建用户态平台导出预设
     * 创建用户态预设；``is_system`` 由 service 强制为 False。
     *
     * 入参 schema 已禁止显式声明 ``is_system``（``extra="forbid"``）；id 缺
     * 省由 service 生成 uuid4().hex；命中唯一约束 → 409。
     * @returns ApiResponse_PlatformExportPresetRead_ Successful Response
     * @throws ApiError
     */
    public static createPlatformExportPresetEndpointApiV1StudioPlatformExportPresetsPost({
        requestBody,
    }: {
        requestBody: PlatformExportPresetCreate,
    }): CancelablePromise<ApiResponse_PlatformExportPresetRead_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/platform-export-presets',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 平台导出预设详情
     * 按 ID 获取预设详情；不存在 → 404。
     * @returns ApiResponse_PlatformExportPresetRead_ Successful Response
     * @throws ApiError
     */
    public static getPlatformExportPresetEndpointApiV1StudioPlatformExportPresetsPresetIdGet({
        presetId,
    }: {
        presetId: string,
    }): CancelablePromise<ApiResponse_PlatformExportPresetRead_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/platform-export-presets/{preset_id}',
            path: {
                'preset_id': presetId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 更新平台导出预设（部分字段）
     * 部分更新；仅写入请求中显式提供的字段；``is_system`` 不开放修改。
     * @returns ApiResponse_PlatformExportPresetRead_ Successful Response
     * @throws ApiError
     */
    public static updatePlatformExportPresetEndpointApiV1StudioPlatformExportPresetsPresetIdPatch({
        presetId,
        requestBody,
    }: {
        presetId: string,
        requestBody: PlatformExportPresetUpdate,
    }): CancelablePromise<ApiResponse_PlatformExportPresetRead_> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/studio/platform-export-presets/{preset_id}',
            path: {
                'preset_id': presetId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 删除平台导出预设（系统预设拒绝删除）
     * 删除预设；命中 ``is_system=True`` 的行直接返回 400。
     * @returns void
     * @throws ApiError
     */
    public static deletePlatformExportPresetEndpointApiV1StudioPlatformExportPresetsPresetIdDelete({
        presetId,
    }: {
        presetId: string,
    }): CancelablePromise<void> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/studio/platform-export-presets/{preset_id}',
            path: {
                'preset_id': presetId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
