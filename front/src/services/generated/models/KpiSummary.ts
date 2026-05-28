/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { KpiRange } from './KpiRange';
/**
 * ``GET /commerce/analytics/kpis`` 响应。
 *
 * 全部字段使用 ``Optional[float]`` —— 在窗口内无任何 outcome 时返回
 * ``None``，由前端显示 "N/A"，避免把"0"误读为"真正发生过、但全部失败"。
 *
 * ROI 当前永远为 ``None``，原因见模块 docstring 的 DESIGN GAP 段。
 */
export type KpiSummary = {
    /**
     * 本次查询的时间窗口
     */
    range: KpiRange;
    /**
     * 窗口内 GMV 总和（人民币元）；窗口为空时为 None
     */
    gmv_total?: (number | null);
    /**
     * ROI = (gmv - estimated_cost) / estimated_cost。成本字段尚未在 StoryVariant 落地（DESIGN GAP），当前永远返回 None。
     */
    roi?: (number | null);
    /**
     * 窗口内 completion_rate_full 平均值（0~1）；无数据时 None
     */
    completion_rate_avg?: (number | null);
    /**
     * 窗口内『加购率』平均值（cart_clicks / plays），分母为 0 的样本被剔除，避免拉爆均值。
     */
    cart_rate_avg?: (number | null);
    /**
     * 窗口内参与聚合的 outcome 行数（用于前端展示置信度）
     */
    sample_size?: number;
};

