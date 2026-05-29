/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_ChapterRead_ } from '../models/ApiResponse_ChapterRead_';
import type { ApiResponse_ChapterTimelineRead_ } from '../models/ApiResponse_ChapterTimelineRead_';
import type { ApiResponse_ChapterTimelineSegmentRead_ } from '../models/ApiResponse_ChapterTimelineSegmentRead_';
import type { ApiResponse_NoneType_ } from '../models/ApiResponse_NoneType_';
import type { ApiResponse_PaginatedData_ChapterRead__ } from '../models/ApiResponse_PaginatedData_ChapterRead__';
import type { ChapterCreate } from '../models/ChapterCreate';
import type { ChapterTimelineSegmentAudioPatch } from '../models/ChapterTimelineSegmentAudioPatch';
import type { ChapterTimelineWrite } from '../models/ChapterTimelineWrite';
import type { ChapterUpdate } from '../models/ChapterUpdate';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class StudioChaptersService {
    /**
     * 获取章节剪辑时间线（含镜头成片解析状态）
     * @returns ApiResponse_ChapterTimelineRead_ Successful Response
     * @throws ApiError
     */
    public static getChapterTimelineApiV1StudioChaptersChapterIdTimelineGet({
        chapterId,
    }: {
        chapterId: string,
    }): CancelablePromise<ApiResponse_ChapterTimelineRead_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/chapters/{chapter_id}/timeline',
            path: {
                'chapter_id': chapterId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 全量保存章节剪辑时间线片段顺序
     * @returns ApiResponse_ChapterTimelineRead_ Successful Response
     * @throws ApiError
     */
    public static putChapterTimelineApiV1StudioChaptersChapterIdTimelinePut({
        chapterId,
        requestBody,
    }: {
        chapterId: string,
        requestBody: ChapterTimelineWrite,
    }): CancelablePromise<ApiResponse_ChapterTimelineRead_> {
        return __request(OpenAPI, {
            method: 'PUT',
            url: '/api/v1/studio/chapters/{chapter_id}/timeline',
            path: {
                'chapter_id': chapterId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * P5 W31-T8：偏量更新单 segment 的 BGM/SFX/ducking 字段
     * 偏量更新本段 BGM/SFX/ducking 字段（不动 layout_version、不动其它段）。
     *
     * 与 ``PUT /timeline``（全量替换）的语义区分：
     * - PUT 改顺序、入出点、字幕/TTS/BGM 等任意字段，``layout_version`` +1；
     * - PATCH 只动一段三列，避免乐观锁误冲突，专给 AVPreviewPanel UI 选 BGM
     * / 拖 ducking 滑块时高频写回使用。
     *
     * 422：``bgm_ducking_db`` 不在 ``[-30, 0]`` 范围内由 Pydantic 自动校验。
     * 404：``chapter_id`` 不存在 / segment 不存在 / segment 不属于该 chapter。
     * W19b 事务边界：service 层只 ``flush``，本路由统一 ``commit``，异常时
     * 整条请求 rollback。
     * @returns ApiResponse_ChapterTimelineSegmentRead_ Successful Response
     * @throws ApiError
     */
    public static patchChapterTimelineSegmentAudioApiV1StudioChaptersChapterIdTimelineSegmentsSegmentIdAudioPatch({
        chapterId,
        segmentId,
        requestBody,
    }: {
        chapterId: string,
        segmentId: string,
        requestBody: ChapterTimelineSegmentAudioPatch,
    }): CancelablePromise<ApiResponse_ChapterTimelineSegmentRead_> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/studio/chapters/{chapter_id}/timeline/segments/{segment_id}/audio',
            path: {
                'chapter_id': chapterId,
                'segment_id': segmentId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 章节列表（分页）
     * @returns ApiResponse_PaginatedData_ChapterRead__ Successful Response
     * @throws ApiError
     */
    public static listChaptersApiV1StudioChaptersGet({
        projectId,
        q,
        order,
        isDesc = false,
        page = 1,
        pageSize = 10,
    }: {
        /**
         * 按项目过滤
         */
        projectId?: (string | null),
        /**
         * 关键字，过滤 title/summary
         */
        q?: (string | null),
        /**
         * 排序字段
         */
        order?: (string | null),
        /**
         * 是否倒序
         */
        isDesc?: boolean,
        page?: number,
        pageSize?: number,
    }): CancelablePromise<ApiResponse_PaginatedData_ChapterRead__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/chapters',
            query: {
                'project_id': projectId,
                'q': q,
                'order': order,
                'is_desc': isDesc,
                'page': page,
                'page_size': pageSize,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 创建章节
     * @returns ApiResponse_ChapterRead_ Successful Response
     * @throws ApiError
     */
    public static createChapterApiV1StudioChaptersPost({
        requestBody,
    }: {
        requestBody: ChapterCreate,
    }): CancelablePromise<ApiResponse_ChapterRead_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/chapters',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 获取章节
     * @returns ApiResponse_ChapterRead_ Successful Response
     * @throws ApiError
     */
    public static getChapterApiV1StudioChaptersChapterIdGet({
        chapterId,
    }: {
        chapterId: string,
    }): CancelablePromise<ApiResponse_ChapterRead_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/chapters/{chapter_id}',
            path: {
                'chapter_id': chapterId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 更新章节
     * @returns ApiResponse_ChapterRead_ Successful Response
     * @throws ApiError
     */
    public static updateChapterApiV1StudioChaptersChapterIdPatch({
        chapterId,
        requestBody,
    }: {
        chapterId: string,
        requestBody: ChapterUpdate,
    }): CancelablePromise<ApiResponse_ChapterRead_> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/studio/chapters/{chapter_id}',
            path: {
                'chapter_id': chapterId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 删除章节
     * @returns ApiResponse_NoneType_ Successful Response
     * @throws ApiError
     */
    public static deleteChapterApiV1StudioChaptersChapterIdDelete({
        chapterId,
    }: {
        chapterId: string,
    }): CancelablePromise<ApiResponse_NoneType_> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/studio/chapters/{chapter_id}',
            path: {
                'chapter_id': chapterId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
