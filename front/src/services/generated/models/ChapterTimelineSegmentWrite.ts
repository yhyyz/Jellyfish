/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 保存时间线时的一段（顺序由数组顺序表达）。
 */
export type ChapterTimelineSegmentWrite = {
    /**
     * 镜头 ID
     */
    shot_id: string;
    /**
     * 裁剪入点毫秒（可选）；与 trim_end_ms 均为空表示全长；否则区间为左闭右开 [start,end)
     */
    trim_start_ms?: (number | null);
    /**
     * 裁剪出点毫秒（exclusive，可选）；为空则默认为源成片时长
     */
    trim_end_ms?: (number | null);
    /**
     * P3 W19：本段渲染好的 .ass 字幕 FileItem ID（W18 shot_subtitle_render_worker 产出），合成阶段 ffmpeg subtitles= 滤镜硬烧到画面
     */
    subtitle_track_file_id?: (string | null);
    /**
     * P3 W19：本段 TTS 合成音频 FileItem ID；audio_strategy=silent_with_tts 时合成阶段 amix 混入
     */
    tts_audio_file_id?: (string | null);
};

