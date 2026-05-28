/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * ``POST /api/v1/commerce/chapter-av-export`` 请求体（P3 W19 / P5 W31）。
 *
 * 触发 ``chapter_av_export`` worker：跨路径合成"配音 + 字幕"成片。
 * 要求章节内所有 Shot.generated_video_file_id 已就位（裸视频已生成），
 * 每段 ChapterTimelineSegment 的 subtitle_track_file_id / tts_audio_file_id
 * 可选——按 audio_strategy 自动分流：silent_with_tts amix TTS、keep_native
 * pass-through 原音；缺 TTS 段降级 anullsrc 静音。
 *
 * P5 W31 新增 ``audio_mix_mode``：控制是否在合成阶段混入 BGM / SFX。
 * 优先级：``audio_mix_mode`` > ``ChapterTimelineSegment.bgm_file_id``
 * / ``sfx_file_id``。当 mode 为 ``voice_bgm`` 但 segment 缺 BGM 时，
 * 本段自动 fallback 到 ``voice_only``（写 warning 不阻塞）。
 */
export type ChapterAvExportRequest = {
    /**
     * 目标章节 ID
     */
    chapter_id: string;
    /**
     * 输出宽高比：9:16（1080×1920）/ 16:9（1280×720）
     */
    aspect?: string;
    /**
     * 覆盖所有镜头 audio_strategy：silent_with_tts / keep_native / null（按各 Shot 字段独立分流）
     */
    audio_strategy_override?: (string | null);
    /**
     * P5 W31：音轨混合模式（off / voice_only / voice_bgm / full）。voice_only=W19 默认；voice_bgm=语音+BGM amix weights='1 0.4'；full=语音+BGM(sidechaincompress ducking)+SFX(amerge 时间轴对齐)；off=完全静音输出。BGM/SFX 来源由各 segment 的 bgm_file_id/sfx_file_id 决定，缺失时自动降级。
     */
    audio_mix_mode?: string;
};

