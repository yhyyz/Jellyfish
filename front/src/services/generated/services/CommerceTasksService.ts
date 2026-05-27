/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_TaskEnqueueResponse_ } from '../models/ApiResponse_TaskEnqueueResponse_';
import type { AsrSubtitleGenerateRequest } from '../models/AsrSubtitleGenerateRequest';
import type { BatchGenerationRequest } from '../models/BatchGenerationRequest';
import type { ChapterAvExportRequest } from '../models/ChapterAvExportRequest';
import type { ChapterAvPlanRequest } from '../models/ChapterAvPlanRequest';
import type { ComplianceCheckRequest } from '../models/ComplianceCheckRequest';
import type { ProductExtractRequest } from '../models/ProductExtractRequest';
import type { ScriptGenerateRequest } from '../models/ScriptGenerateRequest';
import type { ShotSubtitleRenderRequest } from '../models/ShotSubtitleRenderRequest';
import type { TtsGenerateRequest } from '../models/TtsGenerateRequest';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class CommerceTasksService {
    /**
     * 入队：商品信息抽取（异步任务）
     * 收参 → 落 ``GenerationTask`` 行 → commit → Celery 投递 → 返回 task_id。
     *
     * 与 W19b 之前实现的差异：
     * 旧实现把 ``send_task`` 写在 ``service.enqueue_*`` 内部，依赖
     * ``get_db`` 自动 commit；新实现强制路由显式 commit，再 dispatch。
     * @returns ApiResponse_TaskEnqueueResponse_ Successful Response
     * @throws ApiError
     */
    public static enqueueProductExtractApiV1CommerceProductsExtractPost({
        requestBody,
    }: {
        requestBody: ProductExtractRequest,
    }): CancelablePromise<ApiResponse_TaskEnqueueResponse_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/commerce/products/extract',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 入队：剧情脚本生成（异步任务）
     * 收参 → 落 ``GenerationTask`` 行 → commit → Celery 投递 → 返回 task_id。
     * @returns ApiResponse_TaskEnqueueResponse_ Successful Response
     * @throws ApiError
     */
    public static enqueueScriptGenerateApiV1CommerceScriptGeneratePost({
        requestBody,
    }: {
        requestBody: ScriptGenerateRequest,
    }): CancelablePromise<ApiResponse_TaskEnqueueResponse_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/commerce/script-generate',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 入队：合规检查（异步任务）
     * 收参 → 落 ``GenerationTask`` 行 → commit → Celery 投递 → 返回 task_id。
     * @returns ApiResponse_TaskEnqueueResponse_ Successful Response
     * @throws ApiError
     */
    public static enqueueComplianceCheckApiV1CommerceComplianceCheckPost({
        requestBody,
    }: {
        requestBody: ComplianceCheckRequest,
    }): CancelablePromise<ApiResponse_TaskEnqueueResponse_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/commerce/compliance/check',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 批量生成：一次性入队 N 个 story_script_generate 子任务
     * 批量生成入口：把变体网格作为一次性请求落到 ``slow`` 队列上。
     *
     * 路由职责仍保持瘦身：仅做 Pydantic 校验 + 调 service + commit + dispatch
     * + 包响应壳；“一行变体 -> 一个子 ``story_script_generate`` 任务”的真正
     * 编排逻辑在 :func:`app.services.commerce.story_video_batch_generate_worker.run_story_video_batch_generate_task`
     * 里执行，由 worker 在异步链路上完成。
     * @returns ApiResponse_TaskEnqueueResponse_ Successful Response
     * @throws ApiError
     */
    public static enqueueStoryBatchApiV1CommerceStoryBatchesPost({
        requestBody,
    }: {
        requestBody: BatchGenerationRequest,
    }): CancelablePromise<ApiResponse_TaskEnqueueResponse_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/commerce/story-batches',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 入队：章节 AV 决策树（P3 W17）
     * 收参 → 落 ``GenerationTask`` 行 → commit → Celery slow 队列投递 → 返回 task_id。
     *
     * 触发 ``chapter_av_plan`` worker：对章节内所有 ShotDialogLine 跑 Decision F
     * 决策树（estimate → speed_adjust → llm_rewrite → hold），keep_native shot
     * 跳过整树产出 skip_native 决策。
     * @returns ApiResponse_TaskEnqueueResponse_ Successful Response
     * @throws ApiError
     */
    public static enqueueChapterAvPlanApiV1CommerceChapterAvPlanPost({
        requestBody,
    }: {
        requestBody: ChapterAvPlanRequest,
    }): CancelablePromise<ApiResponse_TaskEnqueueResponse_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/commerce/chapter-av-plan',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 入队：TTS 合成（CosyVoice，P3 W17）
     * 收参 → 落 ``GenerationTask`` 行 → commit → Celery fast 队列投递 → 返回 task_id。
     *
     * 触发 ``tts_generate`` worker：用 DashScope CosyVoice 合成单段对白音频，
     * 输出 (audio_file_id, word_timestamps[], cache_hit)；命中 tts_cache 走快
     * 速分支不调供应商。
     * @returns ApiResponse_TaskEnqueueResponse_ Successful Response
     * @throws ApiError
     */
    public static enqueueTtsGenerateApiV1CommerceTtsGeneratePost({
        requestBody,
    }: {
        requestBody: TtsGenerateRequest,
    }): CancelablePromise<ApiResponse_TaskEnqueueResponse_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/commerce/tts/generate',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 入队：ASR 字幕反推（Paraformer-v2，P3 W17 收尾）
     * 收参 → 落 ``GenerationTask`` 行 → commit → Celery fast 队列投递 → 返回 task_id。
     *
     * 触发 ``asr_subtitle_generate`` worker：用 DashScope Paraformer-v2 异步 ASR
     * 反推视频自带音轨的字级时间戳，供 keep_native 路径生成字幕；要求
     * ``video_file_id`` 对应 FileItem 公网可访问。
     * @returns ApiResponse_TaskEnqueueResponse_ Successful Response
     * @throws ApiError
     */
    public static enqueueAsrSubtitleGenerateApiV1CommerceAsrSubtitleGeneratePost({
        requestBody,
    }: {
        requestBody: AsrSubtitleGenerateRequest,
    }): CancelablePromise<ApiResponse_TaskEnqueueResponse_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/commerce/asr-subtitle-generate',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 入队：单镜头字幕渲染（ASS，P3 W18）
     * 收参 → 落 ``GenerationTask`` 行 → commit → Celery fast 队列投递 → 返回 task_id。
     *
     * 触发 ``shot_subtitle_render`` worker：把字级时间戳按 SubtitleStyle 渲染
     * 成 ``.ass`` 文件，落 minio + 写 SubtitleTrack 行；触发安全区 lint，违规
     * 返回 warnings 但不阻塞渲染。
     * @returns ApiResponse_TaskEnqueueResponse_ Successful Response
     * @throws ApiError
     */
    public static enqueueShotSubtitleRenderApiV1CommerceShotSubtitleRenderPost({
        requestBody,
    }: {
        requestBody: ShotSubtitleRenderRequest,
    }): CancelablePromise<ApiResponse_TaskEnqueueResponse_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/commerce/shot-subtitle-render',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 入队：章节级 AV 合成（P3 W19）
     * 收参 → 落 ``GenerationTask`` 行 → commit → Celery slow 队列投递 → 返回 task_id。
     *
     * 触发 ``chapter_av_export`` worker：跨路径合成"配音 + 字幕"成片，按
     * Shot.audio_strategy 分流（silent_with_tts amix TTS / keep_native pass-through
     * 原音）+ ASS 硬烧 + loudnorm 响度归一化；产物落 ``Shot.dubbed_video_file_id``。
     * @returns ApiResponse_TaskEnqueueResponse_ Successful Response
     * @throws ApiError
     */
    public static enqueueChapterAvExportApiV1CommerceChapterAvExportPost({
        requestBody,
    }: {
        requestBody: ChapterAvExportRequest,
    }): CancelablePromise<ApiResponse_TaskEnqueueResponse_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/commerce/chapter-av-export',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
