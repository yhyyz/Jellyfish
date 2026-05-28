/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { Platform } from './Platform';
/**
 * 创建一条 StoryOutcome 的请求体。
 *
 * 字段语义对齐 :class:`app.models.story_formula.StoryOutcome`。``id``
 * 与 ``created_at`` / ``updated_at`` 由数据库自动生成，不接受客户端传入。
 *
 * 校验规则（schema 层硬约束）：
 *
 * * ``gmv``：必须 ≥ 0；负值由 pydantic 直接 422，service 层亦会兜底。
 * * ``completion_rate_3s`` / ``completion_rate_full``：可空；非空时
 * 限制在 ``[0, 1]``。
 * * ``plays`` / ``interactions`` / ``cart_clicks`` / ``orders``：
 * 非负整数；默认 0。
 */
export type StoryOutcomeCreate = {
    /**
     * 所属变体 ID
     */
    variant_id: string;
    /**
     * 投放平台（默认抖音）
     */
    platform?: Platform;
    /**
     * 播放量（BigInteger，避免爆款溢出）
     */
    plays?: number;
    /**
     * 3 秒完播率（0~1，未回传时为 None）
     */
    completion_rate_3s?: (number | null);
    /**
     * 完整完播率（0~1，未回传时为 None）
     */
    completion_rate_full?: (number | null);
    /**
     * 互动量（点赞+评论+分享）
     */
    interactions?: number;
    /**
     * 加购点击
     */
    cart_clicks?: number;
    /**
     * 订单数
     */
    orders?: number;
    /**
     * GMV（人民币）
     */
    gmv?: number;
    /**
     * 备注
     */
    notes?: string;
    /**
     * 平台原始数据 JSON（容忍未来 schema 变化）
     */
    raw_payload?: Record<string, any>;
    /**
     * 数据记录时点（必须 ≤ now，由 service 层兜底）
     */
    recorded_at: string;
};

