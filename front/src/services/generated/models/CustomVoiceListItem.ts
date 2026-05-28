/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 自定义音色列表单项 DTO。
 *
 * 用于 ``GET /api/v1/commerce/voice-packs/custom?clone_status=&limit=&offset=``
 * 分页结果中的每条记录；前端 VoicePackLibrary 列表 + clone_status badge
 * 直接消费。
 */
export type CustomVoiceListItem = {
    /**
     * VoicePack 行主键（clone_xxx 形式）
     */
    id: string;
    /**
     * 用户自定义展示名
     */
    name: string;
    /**
     * TTS 供应商；自定义音色固定为 aliyun_cosyvoice
     */
    provider: string;
    /**
     * DashScope 返回的 voice_id
     */
    provider_voice_id: string;
    /**
     * 语言代码（zh-CN / en-US 等）
     */
    language_code: string;
    /**
     * 声纹性别（一般 neutral）
     */
    gender?: (string | null);
    /**
     * 可选 BrandArchetype 提示
     */
    archetype_hint?: (string | null);
    /**
     * 用户自定义描述
     */
    description?: (string | null);
    /**
     * DashScope 目标合成模型（cosyvoice-v3.5-plus 等）
     */
    target_model?: (string | null);
    /**
     * DashScope 区域端点
     */
    region?: (string | null);
    /**
     * voice clone 状态：deploying / ready / failed / deleted
     */
    clone_status?: (string | null);
    /**
     * ready 时的完成时间戳；其他状态为 NULL
     */
    cloned_at?: (string | null);
    /**
     * 系统级音色标记；自定义音色恒为 false
     */
    is_system: boolean;
    /**
     * UI 列表显示顺序
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

