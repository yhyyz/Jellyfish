/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * ``POST /api/v1/commerce/shot-subtitle-render`` 请求体（P3 W18）。
 *
 * 触发 ``shot_subtitle_render`` worker：把字级时间戳按 SubtitleStyle
 * 渲染成 ``.ass`` 文件，落 minio + SubtitleTrack。
 */
export type ShotSubtitleRenderRequest = {
    /**
     * 字幕所属镜头 ID
     */
    shot_id: string;
    /**
     * SubtitleStyle ID（如 douyin_default / tiktok_viral / reels_lower_third）
     */
    style_id: string;
    /**
     * 字级时间戳数组：[{text, begin_ms, end_ms}, ...]
     */
    word_timestamps: Array<Record<string, any>>;
    /**
     * 字幕语言代码
     */
    language_code?: string;
    /**
     * 来源：tts_word_timestamps / asr_paraformer_v2 / manual
     */
    source?: string;
};

