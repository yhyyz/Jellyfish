/**
 * ByHookChart — 按"钩子模式"维度的归因图表（W22-T3）。
 *
 * 钩子维度 NULL 行被后端剔除，前端不再做兜底过滤。
 */
import React from 'react'
import { Card } from 'antd'

import { PerformanceChart } from '../../../../../components/charts/PerformanceChart'
import { useChartData } from '../queries'
import type { AnalyticsMetric } from '../../../../../services/commerce/analyticsApi'

interface ByHookChartProps {
  metric: AnalyticsMetric
}

export const ByHookChart: React.FC<ByHookChartProps> = ({ metric }) => {
  const query = useChartData('hook', metric)

  return (
    <Card title="按钩子模式归因" data-testid="chart-by-hook">
      <PerformanceChart
        data={query.data?.points ?? []}
        dimension="hook"
        metric={metric}
        chartType="column"
        loading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
      />
    </Card>
  )
}

export default ByHookChart
