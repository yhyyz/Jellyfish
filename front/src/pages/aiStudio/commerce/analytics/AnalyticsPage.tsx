/**
 * AnalyticsPage — A/B 数据归因可视化主页（W22-T3，P4 Wave B 2/11）。
 *
 * 路由 `/commerce/analytics`。
 *
 * 顶部 Segmented 切换 metric（gmv / cart_clicks / completion_rate_full /
 * orders / interactions）；主体 2×2 grid 渲染 4 张归因图。每张图独立的
 * react-query 缓存，metric 切换会同时触发 4 次刷新。
 */
import React, { useState } from 'react'
import { Card, Segmented, Space, Typography } from 'antd'

import { ScrollablePage } from '../../components/ScrollablePage'
import { ByFormulaChart } from './components/ByFormulaChart'
import { ByHookChart } from './components/ByHookChart'
import { ByArchetypeChart } from './components/ByArchetypeChart'
import { ByPlatformChart } from './components/ByPlatformChart'
import { KpiCardsRow } from './components/KpiCardsRow'
import { VariantComparisonTable } from './components/VariantComparisonTable'
import type { AnalyticsMetric } from '../../../../services/commerce/analyticsApi'
import type { KpiRange } from '../../../../services/generated'

const METRIC_OPTIONS: { value: AnalyticsMetric; label: string }[] = [
  { value: 'gmv', label: 'GMV' },
  { value: 'cart_clicks', label: '加购点击' },
  { value: 'completion_rate_full', label: '完播率' },
  { value: 'orders', label: '订单数' },
  { value: 'interactions', label: '互动量' },
]

const RANGE_OPTIONS: { value: KpiRange; label: string }[] = [
  { value: '7d', label: '近 7 天' },
  { value: '30d', label: '近 30 天' },
  { value: '90d', label: '近 90 天' },
]

export const AnalyticsPage: React.FC = () => {
  const [metric, setMetric] = useState<AnalyticsMetric>('gmv')
  const [range, setRange] = useState<KpiRange>('30d')

  return (
    <ScrollablePage className="pr-1">
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Card
          size="small"
          title="窗口"
          extra={
            <Segmented
              aria-label="analytics-range"
              options={RANGE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
              value={range}
              onChange={(v) => setRange(v as KpiRange)}
            />
          }
        >
          <KpiCardsRow range={range} />
        </Card>

        <Card
          title="A/B 数据归因"
          extra={
            <Space>
              <Typography.Text type="secondary">指标</Typography.Text>
              <Segmented
                aria-label="analytics-metric"
                options={METRIC_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
                value={metric}
                onChange={(v) => setMetric(v as AnalyticsMetric)}
              />
            </Space>
          }
        >
          <div
            role="region"
            aria-label="analytics-charts-grid"
            className="grid grid-cols-1 lg:grid-cols-2 gap-3"
          >
            <ByFormulaChart metric={metric} />
            <ByHookChart metric={metric} />
            <ByArchetypeChart metric={metric} />
            <ByPlatformChart metric={metric} />
          </div>
        </Card>

        <Card title="变体对比表">
          <VariantComparisonTable range={range} />
        </Card>
      </Space>
    </ScrollablePage>
  )
}

export default AnalyticsPage
