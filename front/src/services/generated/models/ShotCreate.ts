/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AudioStrategy } from './AudioStrategy';
import type { ProductFocusLevel } from './ProductFocusLevel';
import type { ShotStatus } from './ShotStatus';
export type ShotCreate = {
    /**
     * 镜头 ID
     */
    id: string;
    /**
     * 所属章节 ID
     */
    chapter_id: string;
    /**
     * 镜头序号（章节内唯一）
     */
    index: number;
    /**
     * 镜头标题
     */
    title: string;
    /**
     * 缩略图 URL/路径
     */
    thumbnail?: string;
    /**
     * 镜头状态
     */
    status?: ShotStatus;
    /**
     * 是否明确跳过信息提取
     */
    skip_extraction?: boolean;
    /**
     * 剧本摘录
     */
    script_excerpt?: string;
    /**
     * 已生成视频关联的文件 ID（files.id，type=video）
     */
    generated_video_file_id?: (string | null);
    /**
     * P3 W16/W17：镜头音频策略。silent_with_tts=丢弃模型音轨走 TTS 覆盖；keep_native=保留模型自带原音 + ASR 反推字幕
     */
    audio_strategy?: AudioStrategy;
    /**
     * P3 W16 Decision H：商品视觉聚焦级别。决定 r2v multi_ref 取图角度优先级
     */
    product_focus_level?: ProductFocusLevel;
    /**
     * P3 W19：章节合成（chapter_av_export）输出的'配音+字幕'成片 FileItem ID
     */
    dubbed_video_file_id?: (string | null);
};

