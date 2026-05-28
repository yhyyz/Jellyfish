/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 配额计数读视图。
 *
 * 与 :class:`ApiKeyRead` 共用主表字段，仅聚焦"用了多少 / 还能用多
 * 少"的运营关注面。前端管理面板可基于此渲染配额条 / 告警。
 */
export type ApiKeyUsageRead = {
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
};

