/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 单个聚合数据点。
 */
export type ChartDataPoint = {
    /**
     * 维度稳定主键
     */
    dimension_id: string;
    /**
     * 维度可读名称（用于图表 label）
     */
    dimension_name: string;
    /**
     * 聚合数值；rate 为 [0, 1]，量为 ≥0
     */
    metric_value: number;
};

