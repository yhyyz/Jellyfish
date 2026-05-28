/**
 * KpiCardsRow — AnalyticsPage 顶部 4 张 KPI 卡片（W22-T4，P4 Wave B 3/11）。
 *
 * 数据源 GET /api/v1/commerce/analytics/kpis?range=...，由后端按窗口聚合：
 *   - GMV 总和（SUM）
 *   - ROI（StoryVariant 缺 estimated_cost 字段，永远 None → "N/A"）
 *   - completion_rate_avg（AVG，0~1）
 *   - cart_rate_avg（cart_clicks/plays，分母 0 行剔除）
 *
 * 设计要点：
 * - 空窗口（sample_size=0）时所有数值字段为 null，前端展示 "暂无数据"，
 *   避免把 0 误读为"业务真发生过 0 次"。
 * - range 切换由父组件 (AnalyticsPage) 控制；本组件仅负责展示。
 */
import React from 'react'
import { Card, Col, Row, Statistic, Typography, Empty } from 'antd'
import { useQuery } from '@tanstack/react-query'

import {
  CommerceAnalyticsService,
  type KpiRange,
  type KpiSummary,
} from '../../../../../services/generated'

interface KpiCardsRowProps {
  range: KpiRange
}

const { Text } = Typography

/**
 * 数值格式化：null → "N/A"，rate 类指标乘 100 加 %。
 */
function fmtMoney(v: number | null | undefined): string {
  if (v === null || v === undefined) return 'N/A'
  return `¥${v.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
}

function fmtRate(v: number | null | undefined): string {
  if (v === null || v === undefined) return 'N/A'
  return `${(v * 100).toFixed(2)}%`
}

export const KpiCardsRow: React.FC<KpiCardsRowProps> = ({ range }) => {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['commerce', 'analytics', 'kpis', range],
    queryFn: async () => {
      const res =
        await CommerceAnalyticsService.getAnalyticsKpisApiV1CommerceAnalyticsKpisGet({
          range,
        })
      return res.data as KpiSummary
    },
  })

  if (isError) {
    return (
      <Card size="small">
        <Empty description="KPI 加载失败，请重试" />
      </Card>
    )
  }

  return (
    <Row gutter={16} data-testid="kpi-cards-row">
      <Col span={6}>
        <Card size="small" loading={isLoading}>
          <Statistic
            title="GMV 总额"
            value={fmtMoney(data?.gmv_total)}
            valueStyle={{ fontSize: 22 }}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>
            样本数 {data?.sample_size ?? 0}
          </Text>
        </Card>
      </Col>
      <Col span={6}>
        <Card size="small" loading={isLoading}>
          <Statistic
            title="ROI"
            value={fmtRate(data?.roi)}
            valueStyle={{ fontSize: 22 }}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>
            待 estimated_cost 字段落地后启用
          </Text>
        </Card>
      </Col>
      <Col span={6}>
        <Card size="small" loading={isLoading}>
          <Statistic
            title="平均完播率"
            value={fmtRate(data?.completion_rate_avg)}
            valueStyle={{ fontSize: 22 }}
          />
        </Card>
      </Col>
      <Col span={6}>
        <Card size="small" loading={isLoading}>
          <Statistic
            title="平均加购率"
            value={fmtRate(data?.cart_rate_avg)}
            valueStyle={{ fontSize: 22 }}
          />
        </Card>
      </Col>
    </Row>
  )
}
