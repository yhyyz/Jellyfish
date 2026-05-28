/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_CustomVoiceCreateResponse_ } from '../models/ApiResponse_CustomVoiceCreateResponse_';
import type { ApiResponse_CustomVoiceStatusResponse_ } from '../models/ApiResponse_CustomVoiceStatusResponse_';
import type { ApiResponse_NoneType_ } from '../models/ApiResponse_NoneType_';
import type { ApiResponse_PaginatedData_CustomVoiceListItem__ } from '../models/ApiResponse_PaginatedData_CustomVoiceListItem__';
import type { Body_create_custom_voice_pack_endpoint_api_v1_commerce_voice_packs_custom_post } from '../models/Body_create_custom_voice_pack_endpoint_api_v1_commerce_voice_packs_custom_post';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class CommerceVoicePacksCustomService {
    /**
     * 上传 voice sample 创建自定义音色（异步训练）
     * multipart 接收 sample 文件 + 元信息，链式触发 DashScope create_voice + 异步轮询。
     *
     * 流程：
     * 1. 前置 size cap（``Content-Length`` header，413 早 reject）。
     * 2. 解析 declared_format（从文件名后缀）+ 校验 form 字段（CustomVoiceCreateRequest）。
     * 3. 读取 sample 字节流（受 size cap 限制）。
     * 4. ``validate_audio_metadata`` 二次校验音频元信息。
     * 5. ``upload_sample_to_oss`` 转存到 minio bucket。
     * 6. ``create_voice_remote`` 调 DashScope 拿到 voice_id（仍 DEPLOYING）。
     * 7. ``persist_voice_pack`` 写 VoicePack(is_system=False, clone_status=deploying)
     * + commit（W19b 契约：commit 后才能 dispatch）。
     * 8. ``enqueue_voice_clone_poll`` 落 GenerationTask 行 + commit + dispatch。
     * 9. 返回 ``202 Accepted`` + voice_pack_id。
     * @returns ApiResponse_CustomVoiceCreateResponse_ Successful Response
     * @throws ApiError
     */
    public static createCustomVoicePackEndpointApiV1CommerceVoicePacksCustomPost({
        formData,
    }: {
        formData: Body_create_custom_voice_pack_endpoint_api_v1_commerce_voice_packs_custom_post,
    }): CancelablePromise<ApiResponse_CustomVoiceCreateResponse_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/commerce/voice-packs/custom',
            formData: formData,
            mediaType: 'multipart/form-data',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 自定义音色分页列表（按 clone_status 可选过滤）
     * 列出全部自定义音色（``is_system=False``），按 created_at desc 排序。
     *
     * 默认隐藏 ``deleted`` 状态行，让前端 VoicePackLibrary 不需要客户端再
     * 过滤；显式传 ``clone_status=deleted`` 可访问审计视图。
     * @returns ApiResponse_PaginatedData_CustomVoiceListItem__ Successful Response
     * @throws ApiError
     */
    public static listCustomVoicePacksEndpointApiV1CommerceVoicePacksCustomGet({
        cloneStatus,
        page = 1,
        pageSize = 20,
    }: {
        /**
         * 按 clone_status 精确过滤（deploying / ready / failed / deleted）
         */
        cloneStatus?: (string | null),
        /**
         * 页码（1 起）
         */
        page?: number,
        /**
         * 每页条数
         */
        pageSize?: number,
    }): CancelablePromise<ApiResponse_PaginatedData_CustomVoiceListItem__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/commerce/voice-packs/custom',
            query: {
                'clone_status': cloneStatus,
                'page': page,
                'page_size': pageSize,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 查询单条自定义音色 clone_status（前端轮询用）
     * 查询单条自定义音色当前状态。
     *
     * 前端 VoicePackLibrary 凭此 endpoint 轮询 ``deploying`` 行直到终态
     * （``ready`` / ``failed``）；终态后停止轮询。
     * @returns ApiResponse_CustomVoiceStatusResponse_ Successful Response
     * @throws ApiError
     */
    public static getCustomVoiceStatusEndpointApiV1CommerceVoicePacksCustomVoicePackIdStatusGet({
        voicePackId,
    }: {
        voicePackId: string,
    }): CancelablePromise<ApiResponse_CustomVoiceStatusResponse_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/commerce/voice-packs/custom/{voice_pack_id}/status',
            path: {
                'voice_pack_id': voicePackId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 软删自定义音色 + 释放 DashScope 配额
     * 软删自定义音色：标记 clone_status=deleted + 调 DashScope delete_voice 释放配额。
     *
     * 幂等：voice_pack 不存在时返回 404；DashScope delete_voice 失败时容忍
     * （:func:`delete_voice_remote` 内部捕获），仍把 DB 行标 deleted。
     *
     * 系统级音色（``is_system=True``）禁止删除（403）。
     * @returns ApiResponse_NoneType_ Successful Response
     * @throws ApiError
     */
    public static deleteCustomVoicePackEndpointApiV1CommerceVoicePacksCustomVoicePackIdDelete({
        voicePackId,
    }: {
        voicePackId: string,
    }): CancelablePromise<ApiResponse_NoneType_> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/commerce/voice-packs/custom/{voice_pack_id}',
            path: {
                'voice_pack_id': voicePackId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
