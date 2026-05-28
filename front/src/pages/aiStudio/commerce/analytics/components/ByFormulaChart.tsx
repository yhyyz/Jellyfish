/**
 * ByFormulaChart — 按"剧情公式"维度的归因图表（W22-T3）。
 *
 * 仅承担"取数 + 调通用 PerformanceChart"两件事；空 / 加载 / 错误三态由
 * PerformanceChart 统一兜底。
 */
import React from 'react'
import { Card } from 'antd'

import { PerformanceChart } from '../../../../../components/charts/PerformanceChart'
import { useChartData } from '../queries'
import type { AnalyticsMetric } from '../../../../../services/commerce/analyticsApi'

interface ByFormulaChartProps {
  metric: AnalyticsMetric
}

export const ByFormulaChart: React.FC<ByFormulaChartProps> = ({ metric }) => {
  const query = useChartData('formula', metric)

  return (
    <Card title="按剧情公式归因" data-testid="chart-by-formula">
      <PerformanceChart
        data={query.data?.points ?? []}
        dimension="formula"
        metric={metric}
        chartType="column"
        loading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
      />
    </Card>
  )
}

export default ByFormulaChart
