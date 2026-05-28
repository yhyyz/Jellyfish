/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 更新预设的入参（PATCH 语义）。
 *
 * 全部字段可选，service 层用 ``model_dump(exclude_unset=True)`` 实现
 * "只改传过来的字段"。``is_system`` 不开放修改（系统预设保持系统态）。
 */
export type PlatformExportPresetUpdate = {
    name?: (string | null);
    platform?: (string | null);
    aspect_ratio?: (string | null);
    max_duration_sec?: (number | null);
    subtitle_style_id?: (string | null);
    voice_pack_id?: (string | null);
    watermark_file_id?: (string | null);
    sticker_specs?: null;
    file_format?: (string | null);
    codec_preset?: (string | null);
    loudness_lufs?: (number | null);
    sort_order?: (number | null);
    description?: (string | null);
};

