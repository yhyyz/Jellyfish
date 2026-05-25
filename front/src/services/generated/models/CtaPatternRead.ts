/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * CtaPattern 只读响应。
 *
 * 用于 ``GET /api/v1/studio/cta-patterns`` 列表与详情。``hardness`` 与
 * ``urgency_type`` 同时暴露，供前端做双轴筛选。
 */
export type CtaPatternRead = {
    /**
     * CTA ID（如 scarcity_cta）
     */
    id: string;
    /**
     * 中文名称（如 稀缺紧迫）
     */
    name: string;
    /**
     * 硬度等级：soft / medium / hard
     */
    hardness: string;
    /**
     * 驱动类型：scarcity / urgency / social_proof / benefit / risk_removal
     */
    urgency_type: string;
    /**
     * CTA 说明（运营/UI 展示）
     */
    description: string;
    /**
     * Jinja2 模板片段
     */
    template_text: string;
    /**
     * 样例 CTA 短语列表
     */
    sample_phrases?: Array<string>;
    /**
     * 系统模板标记
     */
    is_system: boolean;
    /**
     * UI 显示排序（升序）
     */
    sort_order: number;
    /**
     * 入库时间
     */
    created_at: string;
};

