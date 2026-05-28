/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { VariantAggregateRow } from './VariantAggregateRow';
/**
 * ``GET /commerce/analytics/variants`` 分页响应壳。
 */
export type VariantAggregateListResponse = {
    items?: Array<VariantAggregateRow>;
    /**
     * 窗口内变体总数（用于前端分页）
     */
    total?: number;
    offset?: number;
    limit?: number;
};

