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
    /**
     * P5 W31：本段 BGM 音轨 FileItem ID（usage_kind=bgm_track）。AudioMixMode in {voice_bgm, full} 时合成阶段混入；voice_only 忽略；为空时 voice_bgm/full 自动 fallback 到 voice_only
     */
    bgm_file_id?: (string | null);
    /**
     * P5 W31：本段 SFX 音轨 FileItem ID（usage_kind=sfx_track）。仅 AudioMixMode=full 合成阶段通过 amerge 加入；为空时 full 自动降级为带 ducking 的 voice_bgm
     */
    sfx_file_id?: (string | null);
    /**
     * P5 W31：full 模式 sidechaincompress 自动 ducking 增益（dB），范围 [-30.0, 0.0]，默认 -12.0；voice_bgm 用静态 weights 不读此字段
     */
    bgm_ducking_db?: number;
};

