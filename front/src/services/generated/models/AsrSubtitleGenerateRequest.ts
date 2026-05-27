/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * ``POST /api/v1/commerce/asr-subtitle-generate`` 请求体（P3 W17 收尾）。
 *
 * 触发 ``asr_subtitle_generate`` worker：用 Paraformer-v2 反推视频/音频
 * 自带音轨的字级时间戳，供 keep_native 路径生成字幕。要求
 * ``video_file_id`` 对应的 FileItem 公网可访问（DashScope 限制）。
 */
export type AsrSubtitleGenerateRequest = {
    /**
     * 源视频 / 音频 FileItem ID
     */
    video_file_id: string;
    /**
     * 语言提示，默认中英混合
     */
    language_hints?: Array<string>;
};

