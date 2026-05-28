/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 创建用户态预设的入参。
 *
 * 系统预设由启动期 bootstrap 幂等管理，本入参不允许声明 ``is_system``
 * 字段（service 层强制 ``is_system=False``）。``id`` 缺省时由 service
 * 生成 ``uuid4().hex``；``platform`` / ``aspect_ratio`` 等关键字段强制
 * 填写。
 */
export type PlatformExportPresetCreate = {
    /**
     * 预设 ID；缺省由 service 生成 uuid4().hex
     */
    id?: (string | null);
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
     * 最大单条时长（秒）
     */
    max_duration_sec: number;
    /**
     * 可选：默认字幕样式 ID
     */
    subtitle_style_id?: (string | null);
    /**
     * 可选：默认音色包 ID
     */
    voice_pack_id?: (string | null);
    /**
     * 可选：水印文件 ID
     */
    watermark_file_id?: (string | null);
    /**
     * 贴纸装配规则数组
     */
    sticker_specs?: Array<Record<string, any>>;
    /**
     * 容器格式
     */
    file_format?: string;
    /**
     * 编码预设
     */
    codec_preset?: string;
    /**
     * 目标响度 LUFS
     */
    loudness_lufs?: number;
    /**
     * 排序权重
     */
    sort_order?: number;
    /**
     * 预设描述
     */
    description?: string;
};

