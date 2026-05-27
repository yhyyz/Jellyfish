/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_list_SubtitleStyleRead__ } from '../models/ApiResponse_list_SubtitleStyleRead__';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class CommerceSubtitleStylesService {
    /**
     * 字幕样式列表（按系统级 / 文件格式 / 项目过滤）
     * 列出 ``subtitle_styles`` 表中的全部记录。
     *
     * 路由职责保持瘦身：收参 → 调 service → ``model_validate`` →
     * ``success_response``，不在此处做业务过滤或字段映射。service 层已把
     * ``alignment`` 换算为 ASS numpad int，本路由直接 dict-validate 即可。
     * @returns ApiResponse_list_SubtitleStyleRead__ Successful Response
     * @throws ApiError
     */
    public static listSubtitleStylesEndpointApiV1CommerceSubtitleStylesGet({
        isSystem,
        format,
        projectId,
    }: {
        /**
         * 是否只列系统级 seed；true=仅系统 / false=仅用户自定义 / 缺省=全部
         */
        isSystem?: (boolean | null),
        /**
         * 按字幕文件格式过滤（ass / srt / vtt）
         */
        format?: (string | null),
        /**
         * 项目级覆盖样式 ID（前向兼容预留，当前 ORM 暂无 project_id 列，传值与不传等价）
         */
        projectId?: (string | null),
    }): CancelablePromise<ApiResponse_list_SubtitleStyleRead__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/commerce/subtitle-styles',
            query: {
                'is_system': isSystem,
                'format': format,
                'project_id': projectId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
