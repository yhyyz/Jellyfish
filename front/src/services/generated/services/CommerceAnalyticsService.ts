/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AnalyticsMetric } from '../models/AnalyticsMetric';
import type { ApiResponse_ChartDataResponse_ } from '../models/ApiResponse_ChartDataResponse_';
import type { ApiResponse_KpiSummary_ } from '../models/ApiResponse_KpiSummary_';
import type { ApiResponse_VariantAggregateListResponse_ } from '../models/ApiResponse_VariantAggregateListResponse_';
import type { KpiRange } from '../models/KpiRange';
import type { VariantSortBy } from '../models/VariantSortBy';
import type { VariantSortDir } from '../models/VariantSortDir';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class CommerceAnalyticsService {
    /**
     * 按剧情公式归因聚合 outcome 指标
     * 按公式 ID 聚合；GMV / 订单 / 加购 / 互动量走 SUM，完播率走 AVG。
     * @returns ApiResponse_ChartDataResponse_ Successful Response
     * @throws ApiError
     */
    public static getAnalyticsByFormulaApiV1CommerceAnalyticsByFormulaGet({
        metric = 'gmv',
    }: {
        /**
         * 指标：gmv / cart_clicks / completion_rate_full / orders / interactions
         */
        metric?: AnalyticsMetric,
    }): CancelablePromise<ApiResponse_ChartDataResponse_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/commerce/analytics/by-formula',
            query: {
                'metric': metric,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 按钩子模式归因聚合 outcome 指标
     * 未指定钩子（``hook_pattern_id IS NULL``）的变体不参与归因。
     * @returns ApiResponse_ChartDataResponse_ Successful Response
     * @throws ApiError
     */
    public static getAnalyticsByHookApiV1CommerceAnalyticsByHookGet({
        metric = 'gmv',
    }: {
        /**
         * 指标
         */
        metric?: AnalyticsMetric,
    }): CancelablePromise<ApiResponse_ChartDataResponse_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/commerce/analytics/by-hook',
            query: {
                'metric': metric,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 按品牌人格归因聚合 outcome 指标
     * ``archetype`` 在变体上为可空字段；NULL 行被过滤。
     * @returns ApiResponse_ChartDataResponse_ Successful Response
     * @throws ApiError
     */
    public static getAnalyticsByArchetypeApiV1CommerceAnalyticsByArchetypeGet({
        metric = 'gmv',
    }: {
        /**
         * 指标
         */
        metric?: AnalyticsMetric,
    }): CancelablePromise<ApiResponse_ChartDataResponse_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/commerce/analytics/by-archetype',
            query: {
                'metric': metric,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 按投放平台归因聚合 outcome 指标
     * ``platform`` 直接落在 outcome 上；不需要 join StoryVariant。
     * @returns ApiResponse_ChartDataResponse_ Successful Response
     * @throws ApiError
     */
    public static getAnalyticsByPlatformApiV1CommerceAnalyticsByPlatformGet({
        metric = 'gmv',
    }: {
        /**
         * 指标
         */
        metric?: AnalyticsMetric,
    }): CancelablePromise<ApiResponse_ChartDataResponse_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/commerce/analytics/by-platform',
            query: {
                'metric': metric,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 顶部 KPI 卡片摘要（GMV / ROI / 完播率 / 加购率）
     * W22-T4：4 张 KPI 卡片所需窗口聚合。
     *
     * ROI 当前永远 None（StoryVariant 缺 ``estimated_cost`` 字段，DESIGN GAP）。
     * 其他指标空窗口返回 None，前端展示 "N/A" 区分"无数据"与"真为 0"。
     * @returns ApiResponse_KpiSummary_ Successful Response
     * @throws ApiError
     */
    public static getAnalyticsKpisApiV1CommerceAnalyticsKpisGet({
        range = '30d',
    }: {
        /**
         * 时间窗口：7d / 30d / 90d
         */
        range?: KpiRange,
    }): CancelablePromise<ApiResponse_KpiSummary_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/commerce/analytics/kpis',
            query: {
                'range': range,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 变体级聚合对比表（server-side 排序+分页）
     * W22-T4：变体级聚合 + 服务端分页 + 排序枚举（防 SQL 注入）。
     * @returns ApiResponse_VariantAggregateListResponse_ Successful Response
     * @throws ApiError
     */
    public static listAnalyticsVariantsApiV1CommerceAnalyticsVariantsGet({
        offset,
        limit = 20,
        sortBy = 'gmv',
        sortDir = 'desc',
        range,
    }: {
        /**
         * 分页偏移
         */
        offset?: number,
        /**
         * 分页大小（最大 100）
         */
        limit?: number,
        /**
         * 排序字段
         */
        sortBy?: VariantSortBy,
        /**
         * 排序方向
         */
        sortDir?: VariantSortDir,
        /**
         * 可选时间窗口；缺省则不限制
         */
        range?: (KpiRange | null),
    }): CancelablePromise<ApiResponse_VariantAggregateListResponse_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/commerce/analytics/variants',
            query: {
                'offset': offset,
                'limit': limit,
                'sort_by': sortBy,
                'sort_dir': sortDir,
                'range': range,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
