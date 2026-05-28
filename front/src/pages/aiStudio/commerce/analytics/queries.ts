/**
 * 归因聚合 TanStack Query hooks（W22-T3，P4 Wave B 2/11）。
 *
 * 把 4 个维度（formula / hook / archetype / platform）+ 5 类指标的查询
 * 收敛到一处。每个维度独立 useQuery，按 ``[..., dimension, metric]`` 缓
 * 存键，便于 metric 切换只重拉对应维度。
 */
import { useQuery } from '@tanstack/react-query'

import {
  analyticsApi,
  type AnalyticsDimension,
  type AnalyticsMetric,
  type ChartDataResponse,
} from '../../../../services/commerce/analyticsApi'

export const analyticsKeys = {
  all: ['commerce', 'analytics'] as const,
  dimension: (dimension: AnalyticsDimension, metric: AnalyticsMetric) =>
    [...analyticsKeys.all, dimension, metric] as const,
}

export function useChartData(dimension: AnalyticsDimension, metric: AnalyticsMetric) {
  return useQuery<ChartDataResponse, Error>({
    queryKey: analyticsKeys.dimension(dimension, metric),
    queryFn: async (): Promise<ChartDataResponse> => {
      switch (dimension) {
        case 'formula':
          return await analyticsApi.byFormula(metric)
        case 'hook':
          return await analyticsApi.byHook(metric)
        case 'archetype':
          return await analyticsApi.byArchetype(metric)
        case 'platform':
          return await analyticsApi.byPlatform(metric)
        default: {
          const exhaustive: never = dimension
          throw new Error(`Unsupported analytics dimension: ${String(exhaustive)}`)
        }
      }
    },
  })
}
