/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * KPI 摘要查询窗口枚举（向后取若干自然日的 outcome）。
 *
 * 选用 7d / 30d / 90d 三档：
 * - 7d：单周快速复盘；
 * - 30d：默认（与运营月度复盘对齐）；
 * - 90d：单季度趋势观察。
 */
export type KpiRange = '7d' | '30d' | '90d';
