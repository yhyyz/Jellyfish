/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_list_VoicePackRead__ } from '../models/ApiResponse_list_VoicePackRead__';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class CommerceVoicePacksService {
    /**
     * 音色包列表（按语言 / 系统级 / 供应商过滤）
     * 列出 ``voice_packs`` 表中的全部记录。
     *
     * 路由职责保持瘦身：收参 → 调 service → ``model_validate`` →
     * ``success_response``，不在此处做业务过滤或字段映射。
     * @returns ApiResponse_list_VoicePackRead__ Successful Response
     * @throws ApiError
     */
    public static listVoicePacksEndpointApiV1CommerceVoicePacksGet({
        languageCode,
        isSystem,
        provider,
    }: {
        /**
         * 按语言代码过滤（如 zh-CN / en-US / ja-JP）
         */
        languageCode?: (string | null),
        /**
         * 是否只列系统级 seed；true=仅系统 / false=仅用户自定义 / 缺省=全部
         */
        isSystem?: (boolean | null),
        /**
         * 按 TTS 供应商过滤（如 aliyun_cosyvoice / openai_tts）
         */
        provider?: (string | null),
    }): CancelablePromise<ApiResponse_list_VoicePackRead__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/commerce/voice-packs',
            query: {
                'language_code': languageCode,
                'is_system': isSystem,
                'provider': provider,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
