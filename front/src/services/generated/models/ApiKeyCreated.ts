/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 创建成功响应（含 *仅本次* 可见的明文）。
 *
 * SaaS 调用方拿到 ``plaintext_key`` 后必须自行妥善保管；服务端不存
 * 储明文，无法二次签发同一明文。
 */
export type ApiKeyCreated = {
    /**
     * API key 明文，**仅创建时本次返回**，后端不存储；丢失后只能创建新的 key
     */
    plaintext_key: string;
    /**
     * bcrypt hash（兼作内部 ID）
     */
    api_key_hash: string;
    /**
     * 备注
     */
    description: string;
    /**
     * 日调用上限
     */
    daily_limit: number;
    /**
     * 月调用上限
     */
    monthly_limit: number;
    /**
     * 每分钟请求上限
     */
    rate_per_minute: number;
    /**
     * 是否启用（创建时默认 true）
     */
    is_active: boolean;
    /**
     * 创建时间
     */
    created_at: string;
};

