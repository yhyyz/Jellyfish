/**
 * PerformanceChart — 通用归因图表 wrapper（W22-T3，P4 Wave B 2/11）。
 *
 * 让 4 个归因图表（按 formula / hook / archetype / platform）共享同一份
 * 数据 → 图表的渲染逻辑。三态：loading → Skeleton；error → Alert + 重试；
 * 空集合 → Empty。落地图表组件只负责传入聚合好的数据。
 *
 * 仅依赖 antd-charts v2 的 `Column` / `Line` / `Pie` 三种内置组件，主题
 * 走 `theme="academy"` 继承 antd 的 token 颜色。
 */
import React from 'react'
import { Alert, Button, Empty, Skeleton } from 'antd'
import { Column, Line, Pie } from '@ant-design/charts'

import type { ChartDataPoint } from '../../services/generated'

export type PerformanceChartType = 'column' | 'line' | 'pie'

export interface PerformanceChartProps {
  data: ChartDataPoint[]
  dimension: string
  metric: string
  chartType?: PerformanceChartType
  loading?: boolean
  error?: Error | null
  onRetry?: () => void
  height?: number
}

const COMMON_THEME = 'academy'

export const PerformanceChart: React.FC<PerformanceChartProps> = ({
  data,
  dimension,
  metric,
  chartType = 'column',
  loading,
  error,
  onRetry,
  height = 320,
}) => {
  if (loading) {
    return (
      <div
        role="status"
        aria-label={`${dimension}-${metric}-loading`}
        style={{ minHeight: height }}
      >
        <Skeleton active paragraph={{ rows: 4 }} />
      </div>
    )
  }

  if (error) {
    return (
      <Alert
        type="error"
        showIcon
        message={`${metric} 数据加载失败`}
        description={error.message}
        action={
          onRetry ? (
            <Button size="small" onClick={onRetry}>
              重试
            </Button>
          ) : undefined
        }
      />
    )
  }

  if (!data || data.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={`暂无 ${dimension} 维度的 ${metric} 数据`}
        style={{ padding: 32 }}
      />
    )
  }

  if (chartType === 'pie') {
    return (
      <div role="img" aria-label={`${dimension}-${metric}-pie`} style={{ minHeight: height }}>
        <Pie
          data={data}
          angleField="metric_value"
          colorField="dimension_name"
          label={{ text: 'dimension_name' }}
          theme={COMMON_THEME}
          height={height}
        />
      </div>
    )
  }

  if (chartType === 'line') {
    return (
      <div role="img" aria-label={`${dimension}-${metric}-line`} style={{ minHeight: height }}>
        <Line
          data={data}
          xField="dimension_name"
          yField="metric_value"
          point={{ shapeField: 'circle', sizeField: 4 }}
          theme={COMMON_THEME}
          height={height}
        />
      </div>
    )
  }

  return (
    <div role="img" aria-label={`${dimension}-${metric}-column`} style={{ minHeight: height }}>
      <Column
        data={data}
        xField="dimension_name"
        yField="metric_value"
        colorField="dimension_name"
        legend={false}
        theme={COMMON_THEME}
        height={height}
      />
    </div>
  )
}

export default PerformanceChart
