/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type Body_create_custom_voice_pack_endpoint_api_v1_commerce_voice_packs_custom_post = {
    /**
     * voice sample 音频文件（wav / mp3 / m4a，<=10 MB，10-60 秒）
     */
    sample_file: string;
    /**
     * DashScope voice clone prefix；<=10 字符，仅数字/字母/下划线
     */
    prefix: string;
    /**
     * DashScope 目标合成模型（cosyvoice-v3.5-plus / cosyvoice-v3-plus）
     */
    target_model: string;
    /**
     * DashScope 区域端点（cn-beijing / ap-singapore）
     */
    region: string;
    /**
     * 用户可见的音色展示名称
     */
    display_name: string;
    /**
     * 可选 language hints（逗号分隔，如 'zh' 或 'en,fr'）
     */
    language_hints?: (string | null);
    /**
     * 可选业务描述（<=255 字符）
     */
    description?: (string | null);
    /**
     * 可选 BrandArchetype 提示
     */
    archetype_hint?: (string | null);
};

