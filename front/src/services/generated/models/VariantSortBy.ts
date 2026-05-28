/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 变体对比表的可排序字段。
 *
 * 与 :class:`VariantAggregateRow` 的可数值字段一一对应；前端 antd Table
 * 的 sorter 会把 columnKey 映射为该枚举，避免前端任意 SQL 注入。
 */
export type VariantSortBy = 'gmv' | 'plays' | 'cart_clicks' | 'orders' | 'completion_rate_full' | 'cart_rate' | 'recorded_at';
