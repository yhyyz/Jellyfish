/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_list_StoryVariantRead__ } from '../models/ApiResponse_list_StoryVariantRead__';
import type { ApiResponse_StoryVariantRead_ } from '../models/ApiResponse_StoryVariantRead_';
import type { StoryVariantCreate } from '../models/StoryVariantCreate';
import type { StoryVariantStatus } from '../models/StoryVariantStatus';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class StudioStoryVariantsService {
    /**
     * 变体列表（按 project_id 必填过滤，按 created_at desc 排序）
     * 按 project_id 过滤变体列表。
     * @returns ApiResponse_list_StoryVariantRead__ Successful Response
     * @throws ApiError
     */
    public static listStoryVariantsApiV1StudioStoryVariantsGet({
        projectId,
        chapterId,
        status,
    }: {
        /**
         * 项目 ID（必填）
         */
        projectId: string,
        /**
         * 章节 ID（可选过滤）
         */
        chapterId?: (string | null),
        /**
         * 变体状态（可选过滤）
         */
        status?: (StoryVariantStatus | null),
    }): CancelablePromise<ApiResponse_list_StoryVariantRead__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/story-variants',
            query: {
                'project_id': projectId,
                'chapter_id': chapterId,
                'status': status,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 手动创建变体（status=draft，自动生成 id）
     * 手动创建变体；P1 阶段不走自动化生成路径。
     * @returns ApiResponse_StoryVariantRead_ Successful Response
     * @throws ApiError
     */
    public static createStoryVariantApiV1StudioStoryVariantsPost({
        requestBody,
    }: {
        requestBody: StoryVariantCreate,
    }): CancelablePromise<ApiResponse_StoryVariantRead_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/story-variants',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
