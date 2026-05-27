/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { DialogueLineMode } from './DialogueLineMode';
export type ShotDialogLineRead = {
    /**
     * 对话行 ID
     */
    id: number;
    /**
     * 所属镜头细节 ID
     */
    shot_detail_id: string;
    /**
     * 行号（镜头内排序）
     */
    index?: number;
    /**
     * 台词内容
     */
    text: string;
    /**
     * 对白模式
     */
    line_mode?: DialogueLineMode;
    /**
     * 说话角色 ID
     */
    speaker_character_id?: (string | null);
    /**
     * 听者角色 ID
     */
    target_character_id?: (string | null);
    /**
     * 说话角色名称（用于回填关联；可空）
     */
    speaker_name?: (string | null);
    /**
     * 听者角色名称（用于回填关联；可空）
     */
    target_name?: (string | null);
    /**
     * P3 W17：本行强制使用的音色 voice_pack ID（覆盖角色默认）
     */
    tts_voice_id?: (string | null);
    /**
     * P3 W17：本行 TTS 合成结果音频 FileItem ID（命中 tts_cache 时回填）
     */
    tts_audio_file_id?: (string | null);
    /**
     * P3 W17：对白在镜头时间线内的起始毫秒（chapter_av_planner 写入）
     */
    start_time_ms?: (number | null);
    /**
     * P3 W17：对白结束毫秒；end - start = TTS 音频时长上限
     */
    end_time_ms?: (number | null);
};

