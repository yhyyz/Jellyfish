/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * VoicePack 只读响应。
 *
 * 用于 ``GET /api/v1/commerce/voice-packs`` 列表接口。字段直接映射自
 * ORM 列；Enum 列（``provider`` / ``gender``）在 ORM 层已是 ``str``
 * 化的枚举值，pydantic 直接读取即可。
 */
export type VoicePackRead = {
    /**
     * 音色包 ID（如 cosyvoice_v2_longxiaochun）
     */
    id: string;
    /**
     * 展示名称（如 龙小淳）
     */
    name: string;
    /**
     * TTS 供应商（aliyun_cosyvoice / openai_tts）
     */
    provider: string;
    /**
     * 供应商侧音色 ID（如 longxiaochun_v2）
     */
    provider_voice_id: string;
    /**
     * 语言代码（zh-CN / en-US / ja-JP 等）
     */
    language_code: string;
    /**
     * 声纹性别（male / female / neutral / child）
     */
    gender?: (string | null);
    /**
     * 与 BrandArchetype 的语义匹配提示（如 sage / elder）
     */
    archetype_hint?: (string | null);
    /**
     * 试听样本音频 file_id；自定义克隆音色为训练样本
     */
    sample_file_id?: (string | null);
    /**
     * 音色描述（适用场景、特质等）
     */
    description?: (string | null);
    /**
     * 默认语速（0.5-2.0），TTS 估时长用
     */
    default_speed: number;
    /**
     * 系统级音色标记，true 时不可被用户删除
     */
    is_system: boolean;
    /**
     * UI 列表显示顺序（升序）
     */
    sort_order: number;
    /**
     * 入库时间
     */
    created_at: string;
    /**
     * 最近一次更新时间
     */
    updated_at: string;
};

