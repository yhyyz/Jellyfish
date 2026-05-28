/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AnalyticsMetric } from '../models/AnalyticsMetric';
import type { ApiResponse_ChartDataResponse_ } from '../models/ApiResponse_ChartDataResponse_';
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
}
