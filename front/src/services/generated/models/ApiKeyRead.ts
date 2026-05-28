/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * API key 读视图。
 *
 * 用于 ``GET /api/v1/settings/api-keys`` 列表与详情，永远不含明文
 * 字段。``model_config`` 启用 ``from_attributes`` 让路由层可以
 * ``ApiKeyRead.model_validate(orm_row)`` 一键序列化。
 */
export type ApiKeyRead = {
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
     * 今日已消耗
     */
    consumed_today: number;
    /**
     * 本月已消耗
     */
    consumed_this_month: number;
    /**
     * 上次日重置日期
     */
    last_reset_daily: string;
    /**
     * 上次月重置日期
     */
    last_reset_monthly: string;
    /**
     * 是否启用
     */
    is_active: boolean;
    /**
     * 创建时间
     */
    created_at: string;
    /**
     * 最近更新时间
     */
    updated_at: string;
};

