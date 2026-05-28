/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * StoryOutcome 只读响应。
 *
 * Enum 字段（``platform``）在序列化时降级为字符串，前端可直接渲染。
 */
export type StoryOutcomeRead = {
    /**
     * 自增主键
     */
    id: number;
    /**
     * 所属变体 ID
     */
    variant_id: string;
    /**
     * 投放平台（枚举值字符串）
     */
    platform: string;
    /**
     * 播放量
     */
    plays: number;
    /**
     * 3 秒完播率
     */
    completion_rate_3s?: (number | null);
    /**
     * 完整完播率
     */
    completion_rate_full?: (number | null);
    /**
     * 互动量
     */
    interactions: number;
    /**
     * 加购点击
     */
    cart_clicks: number;
    /**
     * 订单数
     */
    orders: number;
    /**
     * GMV
     */
    gmv: number;
    /**
     * 备注
     */
    notes: string;
    /**
     * 平台原始数据 JSON
     */
    raw_payload?: Record<string, any>;
    /**
     * 数据记录时点
     */
    recorded_at: string;
    /**
     * 创建时间
     */
    created_at?: (string | null);
    /**
     * 最近更新时间
     */
    updated_at?: (string | null);
};

