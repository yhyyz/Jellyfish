/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { TimelineClipStatus } from './TimelineClipStatus';
/**
 * 时间线片段读取模型（含成片文件解析状态）。
 */
export type ChapterTimelineSegmentRead = {
    /**
     * 片段行 ID；尚未落库的合成行可为空字符串
     */
    id: string;
    shot_id: string;
    position: number;
    /**
     * 已保存入点毫秒；null 表示从 0
     */
    trim_start_ms?: (number | null);
    /**
     * 已保存出点毫秒（exclusive）；null 表示至片尾
     */
    trim_end_ms?: (number | null);
    /**
     * P3 W19：本段字幕 .ass 文件 FileItem ID（chapter_av_export 烧录用）
     */
    subtitle_track_file_id?: (string | null);
    /**
     * P3 W19：本段 TTS 音频 FileItem ID（silent_with_tts 路径混入）
     */
    tts_audio_file_id?: (string | null);
    /**
     * P5 W31：本段 BGM FileItem ID（voice_bgm/full 模式混入）
     */
    bgm_file_id?: (string | null);
    /**
     * P5 W31：本段 SFX FileItem ID（仅 full 模式 amerge 加入）
     */
    sfx_file_id?: (string | null);
    /**
     * P5 W31：full 模式 sidechaincompress ducking 增益（dB）
     */
    bgm_ducking_db?: number;
    clip_status: TimelineClipStatus;
    file_id?: (string | null);
    /**
     * 镜头标题等展示字段
     */
    label?: string;
};

