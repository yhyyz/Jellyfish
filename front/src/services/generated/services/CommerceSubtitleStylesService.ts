/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_list_SubtitleStyleRead__ } from '../models/ApiResponse_list_SubtitleStyleRead__';
import type { ApiResponse_NoneType_ } from '../models/ApiResponse_NoneType_';
import type { ApiResponse_SubtitleStyleRead_ } from '../models/ApiResponse_SubtitleStyleRead_';
import type { ProjectSubtitleStyleCreateInput } from '../models/ProjectSubtitleStyleCreateInput';
import type { ProjectSubtitleStyleUpdateInput } from '../models/ProjectSubtitleStyleUpdateInput';
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
         * 项目级覆盖样式 ID 过滤（W30：传值缩窄到该 project 的覆盖样式；缺省时返回系统级 + 全部项目级）
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
    /**
     * 项目级 merged 字幕样式视图（系统级 + 项目级覆盖）
     * 列出指定 project 视角下的字幕样式 merged 视图。
     *
     * merged 语义：项目级同名行覆盖系统级 seed；项目级独有 name 单独列出。
     * @returns ApiResponse_list_SubtitleStyleRead__ Successful Response
     * @throws ApiError
     */
    public static listProjectSubtitleStylesEndpointApiV1CommerceProjectsProjectIdSubtitleStylesGet({
        projectId,
    }: {
        projectId: string,
    }): CancelablePromise<ApiResponse_list_SubtitleStyleRead__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/commerce/projects/{project_id}/subtitle-styles',
            path: {
                'project_id': projectId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 创建项目级覆盖字幕样式
     * 创建一条项目级覆盖样式行。
     *
     * 业务约束：
     * - ``project_id`` 必须存在（404 if not found）；
     * - 同 project 内 ``name`` 唯一（409 on conflict）；
     * - 系统级行的 POST 路径不存在（仅项目 path 可创建项目级行）。
     * @returns ApiResponse_SubtitleStyleRead_ Successful Response
     * @throws ApiError
     */
    public static createProjectSubtitleStyleEndpointApiV1CommerceProjectsProjectIdSubtitleStylesPost({
        projectId,
        requestBody,
        authorization,
    }: {
        projectId: string,
        requestBody: ProjectSubtitleStyleCreateInput,
        authorization?: (string | null),
    }): CancelablePromise<ApiResponse_SubtitleStyleRead_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/commerce/projects/{project_id}/subtitle-styles',
            path: {
                'project_id': projectId,
            },
            headers: {
                'authorization': authorization,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 更新项目级覆盖字幕样式
     * 部分更新项目级覆盖样式。
     *
     * 业务约束：
     * - 系统级行（``project_id IS NULL``）→ 403 immutable；
     * - 行不存在 / 行不属于该 project → 404；
     * - rename 后与同 project 内已有 name 冲突 → 409。
     * @returns ApiResponse_SubtitleStyleRead_ Successful Response
     * @throws ApiError
     */
    public static updateProjectSubtitleStyleEndpointApiV1CommerceProjectsProjectIdSubtitleStylesStyleIdPatch({
        projectId,
        styleId,
        requestBody,
        authorization,
    }: {
        projectId: string,
        styleId: string,
        requestBody: ProjectSubtitleStyleUpdateInput,
        authorization?: (string | null),
    }): CancelablePromise<ApiResponse_SubtitleStyleRead_> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/commerce/projects/{project_id}/subtitle-styles/{style_id}',
            path: {
                'project_id': projectId,
                'style_id': styleId,
            },
            headers: {
                'authorization': authorization,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 删除项目级覆盖字幕样式（重置为系统模板）
     * 删除项目级覆盖样式行。
     *
     * 删除后下次渲染会自动 fallback 系统级；已渲染的 SubtitleTrack
     * 保留 SET NULL 引用（W18 ORM ``ondelete='SET NULL'``），不会出现悬挂错误。
     *
     * 业务约束同 PATCH：系统级 immutable / 行归属校验。
     * @returns ApiResponse_NoneType_ Successful Response
     * @throws ApiError
     */
    public static deleteProjectSubtitleStyleEndpointApiV1CommerceProjectsProjectIdSubtitleStylesStyleIdDelete({
        projectId,
        styleId,
        authorization,
    }: {
        projectId: string,
        styleId: string,
        authorization?: (string | null),
    }): CancelablePromise<ApiResponse_NoneType_> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/commerce/projects/{project_id}/subtitle-styles/{style_id}',
            path: {
                'project_id': projectId,
                'style_id': styleId,
            },
            headers: {
                'authorization': authorization,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
