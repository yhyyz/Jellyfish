/**
 * ByPlatformChart — 按"投放平台"维度的归因图表（W22-T3）。
 *
 * 平台维度量级差距大（抖音 vs 快手 vs 小红书），柱状图便于比绝对量。
 */
import React from 'react'
import { Card } from 'antd'

import { PerformanceChart } from '../../../../../components/charts/PerformanceChart'
import { useChartData } from '../queries'
import type { AnalyticsMetric } from '../../../../../services/commerce/analyticsApi'

interface ByPlatformChartProps {
  metric: AnalyticsMetric
}

export const ByPlatformChart: React.FC<ByPlatformChartProps> = ({ metric }) => {
  const query = useChartData('platform', metric)

  return (
    <Card title="按投放平台归因" data-testid="chart-by-platform">
      <PerformanceChart
        data={query.data?.points ?? []}
        dimension="platform"
        metric={metric}
        chartType="column"
        loading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
      />
    </Card>
  )
}

export default ByPlatformChart
