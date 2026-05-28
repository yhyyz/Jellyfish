/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 创建 API key 的请求体。
 *
 * 所有字段都给了运营友好默认值（沿用
 * :class:`app.models.api_quota.ApiKeyQuota` server_default），方便管
 * 理面板「直接创建」一键生成可用 key。
 */
export type ApiKeyCreateRequest = {
    /**
     * key 用途备注，便于在管理面板辨认归属
     */
    description?: string;
    /**
     * 日调用上限；0 表示禁用调用
     */
    daily_limit?: number;
    /**
     * 月调用上限；0 表示禁用调用
     */
    monthly_limit?: number;
    /**
     * 每分钟请求数上限（限流参数，由后续中间件消费）
     */
    rate_per_minute?: number;
};

