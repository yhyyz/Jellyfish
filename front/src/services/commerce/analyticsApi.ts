/**
 * 归因聚合 API 薄 wrapper（W22-T3，P4 Wave B 2/11）。
 *
 * 严守 AGENTS.md 第 2 条：所有后端调用统一走 OpenAPI generated client。
 * 本文件把冗长方法名收敛为 ``analyticsApi.byFormula / byHook / ...``，
 * 并统一从 ``ApiResponse.data`` 解包出 ChartDataResponse。
 */
import {
  CommerceAnalyticsService,
  type AnalyticsDimension,
  type AnalyticsMetric,
  type ChartDataResponse,
} from '../generated'

function emptyResponse(
  dimension: AnalyticsDimension,
  metric: AnalyticsMetric,
): ChartDataResponse {
  return { dimension, metric, points: [] }
}

export const analyticsApi = {
  async byFormula(metric: AnalyticsMetric): Promise<ChartDataResponse> {
    const res =
      await CommerceAnalyticsService.getAnalyticsByFormulaApiV1CommerceAnalyticsByFormulaGet({
        metric,
      })
    return res.data ?? emptyResponse('formula' as AnalyticsDimension, metric)
  },

  async byHook(metric: AnalyticsMetric): Promise<ChartDataResponse> {
    const res =
      await CommerceAnalyticsService.getAnalyticsByHookApiV1CommerceAnalyticsByHookGet({
        metric,
      })
    return res.data ?? emptyResponse('hook' as AnalyticsDimension, metric)
  },

  async byArchetype(metric: AnalyticsMetric): Promise<ChartDataResponse> {
    const res =
      await CommerceAnalyticsService.getAnalyticsByArchetypeApiV1CommerceAnalyticsByArchetypeGet({
        metric,
      })
    return res.data ?? emptyResponse('archetype' as AnalyticsDimension, metric)
  },

  async byPlatform(metric: AnalyticsMetric): Promise<ChartDataResponse> {
    const res =
      await CommerceAnalyticsService.getAnalyticsByPlatformApiV1CommerceAnalyticsByPlatformGet({
        metric,
      })
    return res.data ?? emptyResponse('platform' as AnalyticsDimension, metric)
  },
}

export type { AnalyticsDimension, AnalyticsMetric, ChartDataResponse }
