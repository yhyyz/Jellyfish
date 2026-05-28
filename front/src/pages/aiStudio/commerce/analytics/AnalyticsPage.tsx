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
import type { AnalyticsMetric } from '../../../../services/commerce/analyticsApi'

const METRIC_OPTIONS: { value: AnalyticsMetric; label: string }[] = [
  { value: 'gmv', label: 'GMV' },
  { value: 'cart_clicks', label: '加购点击' },
  { value: 'completion_rate_full', label: '完播率' },
  { value: 'orders', label: '订单数' },
  { value: 'interactions', label: '互动量' },
]

export const AnalyticsPage: React.FC = () => {
  const [metric, setMetric] = useState<AnalyticsMetric>('gmv')

  return (
    <ScrollablePage className="pr-1">
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
    </ScrollablePage>
  )
}

export default AnalyticsPage
