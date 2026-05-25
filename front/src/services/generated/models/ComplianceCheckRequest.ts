/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * ``POST /api/v1/commerce/compliance/check`` 请求体。
 *
 * 合规检查要么针对“某个具体变体的当前剧本”，要么针对“调用方手里
 * 临时拼出的脚本片段”。``script_text`` 留为可选字段：worker 在 None
 * 时会按 ``variant_id`` 回查最新剧本；非空时直接使用该字符串，避免
 * 一些“想看看新文案是否合规”的轻量调试场景被强制要求改写到 DB。
 *
 * Attributes:
 * variant_id: 变体 ID，作为 ``ComplianceFinding.variant_id`` 外键。
 * region: 适用合规地域（与 ``ComplianceProfile.region`` 对齐）。
 * product_category: 商品品类，影响是否触发健康/食品等专项规则。
 * script_text: 待校验的脚本文本；为 ``None`` 时 worker 回查变体当前剧本。
 * script_duration_sec: 脚本对应的视频时长（秒），用于判定品牌口播频次。
 * brand_aliases: 品牌别名（含商品名/品类俚语），影响品牌频次规则命中。
 */
export type ComplianceCheckRequest = {
    /**
     * 所属变体 ID
     */
    variant_id: string;
    /**
     * 合规地域，默认 cn_mainland
     */
    region?: string;
    /**
     * 商品品类，默认 other
     */
    product_category?: string;
    /**
     * 待校验脚本文本；为空时 worker 回查变体当前剧本
     */
    script_text?: (string | null);
    /**
     * 脚本对应视频时长（秒）
     */
    script_duration_sec?: number;
    /**
     * 品牌别名列表（含商品名/俚语）
     */
    brand_aliases?: Array<string>;
};

