/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * ``POST /api/v1/commerce/export`` 请求体。
 *
 * Attributes:
 * variant_id: 目标 :class:`StoryVariant` ID；worker 据此回查关联章节
 * 的 chapter_av_export 产物 mp4。
 * preset_id: 目标 :class:`PlatformExportPreset` ID（如
 * ``douyin_default`` / ``tiktok_default``），worker 据此装配
 * ffmpeg 转换参数。
 */
export type CommerceExportRequest = {
    /**
     * 目标 StoryVariant ID（commerce 视频变体主键）
     */
    variant_id: string;
    /**
     * 目标 PlatformExportPreset ID（如 douyin_default / tiktok_default / xiaohongshu_default 等）
     */
    preset_id: string;
};

