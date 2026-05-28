/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * PlatformExportPreset 通用响应。
 *
 * 用于 ``GET / POST / PATCH /api/v1/studio/platform-export-presets*``
 * 的成功响应数据 ``data`` 字段；字段直接映射自 ORM 列。
 */
export type PlatformExportPresetRead = {
    /**
     * 预设 ID（如 douyin_default / tiktok_default）
     */
    id: string;
    /**
     * 展示名称
     */
    name: string;
    /**
     * 目标投放平台（douyin / kuaishou / xiaohongshu / youtube / tiktok）
     */
    platform: string;
    /**
     * 画幅比例（9:16 / 1:1 / 16:9）
     */
    aspect_ratio: string;
    /**
     * 平台允许的最大单条时长（秒）
     */
    max_duration_sec: number;
    /**
     * 可选：默认字幕样式 ID（关联 subtitle_styles.id）
     */
    subtitle_style_id?: (string | null);
    /**
     * 可选：默认音色包 ID（关联 voice_packs.id）
     */
    voice_pack_id?: (string | null);
    /**
     * 可选：水印 PNG/SVG 的 FileItem ID（关联 files.id）
     */
    watermark_file_id?: (string | null);
    /**
     * 贴纸装配规则数组 [{type, position, asset_id}, ...]
     */
    sticker_specs?: Array<Record<string, any>>;
    /**
     * 导出容器格式（mp4 / mov）
     */
    file_format: string;
    /**
     * 编码预设（h264_high_4_1 等）
     */
    codec_preset: string;
    /**
     * 目标响度 LUFS（负值）
     */
    loudness_lufs: number;
    /**
     * 系统级预设标记，true 时不可被业务层删除
     */
    is_system: boolean;
    /**
     * UI 列表排序权重（升序）
     */
    sort_order: number;
    /**
     * 预设描述（运营备注）
     */
    description?: string;
    /**
     * 入库时间
     */
    created_at: string;
    /**
     * 最近一次更新时间
     */
    updated_at: string;
};

