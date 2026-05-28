/**
 * ByArchetypeChart — 按"品牌人格"维度的归因图表（W22-T3）。
 *
 * 品牌人格通常 ≤12 类，分布对比偏向"占比 vs 量级"，因此默认 Pie 形态
 * 直观展示哪个 archetype 拿走了多少 GMV / 完播率份额。
 */
import React from 'react'
import { Card } from 'antd'

import { PerformanceChart } from '../../../../../components/charts/PerformanceChart'
import { useChartData } from '../queries'
import type { AnalyticsMetric } from '../../../../../services/commerce/analyticsApi'

interface ByArchetypeChartProps {
  metric: AnalyticsMetric
}

export const ByArchetypeChart: React.FC<ByArchetypeChartProps> = ({ metric }) => {
  const query = useChartData('archetype', metric)

  return (
    <Card title="按品牌人格归因" data-testid="chart-by-archetype">
      <PerformanceChart
        data={query.data?.points ?? []}
        dimension="archetype"
        metric={metric}
        chartType="pie"
        loading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
      />
    </Card>
  )
}

export default ByArchetypeChart
