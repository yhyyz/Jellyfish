/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AnalyticsDimension } from './AnalyticsDimension';
import type { AnalyticsMetric } from './AnalyticsMetric';
import type { ChartDataPoint } from './ChartDataPoint';
/**
 * 归因聚合响应壳。
 */
export type ChartDataResponse = {
    dimension: AnalyticsDimension;
    metric: AnalyticsMetric;
    points?: Array<ChartDataPoint>;
};

