/**
 * VariantComparisonTable — AnalyticsPage 变体对比表（W22-T4，P4 Wave B 3/11）。
 *
 * 数据源 GET /api/v1/commerce/analytics/variants（server-side 排序+分页）。
 * 后端定义 sort_by 枚举 (gmv/plays/cart_clicks/orders/completion_rate_full/
 * cart_rate/recorded_at)，前端 antd Table 的 sorter columnKey 须严格对齐
 * 该枚举名，避免 SQL 注入风险。
 *
 * 设计要点：
 * - cart_rate 由后端 SQL 端 NULLIF 防 0，前端不二次除法
 * - 展示字段裁剪：完播率/加购率乘 100 加 %；NULL 字段显示 "—"
 */
import React, { useState } from 'react'
import { Table, Card } from 'antd'
import type { TableProps } from 'antd'
import { useQuery } from '@tanstack/react-query'

import {
  CommerceAnalyticsService,
  type KpiRange,
  type VariantAggregateRow,
} from '../../../../../services/generated'

interface VariantComparisonTableProps {
  range?: KpiRange
}

type SortBy =
  | 'gmv'
  | 'plays'
  | 'cart_clicks'
  | 'orders'
  | 'completion_rate_full'
  | 'cart_rate'
  | 'recorded_at'

type SortDir = 'asc' | 'desc'

function fmtRate(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return `${(v * 100).toFixed(2)}%`
}

function fmtMoney(v: number | null | undefined): string {
  if (v === null || v === undefined || v === 0) return '0'
  return v.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

export const VariantComparisonTable: React.FC<VariantComparisonTableProps> = ({
  range,
}) => {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [sortBy, setSortBy] = useState<SortBy>('gmv')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const offset = (page - 1) * pageSize

  const { data, isLoading } = useQuery({
    queryKey: [
      'commerce',
      'analytics',
      'variants',
      { offset, limit: pageSize, sortBy, sortDir, range },
    ],
    queryFn: async () => {
      const res =
        await CommerceAnalyticsService.listAnalyticsVariantsApiV1CommerceAnalyticsVariantsGet(
          {
            offset,
            limit: pageSize,
            sortBy: sortBy as never,
            sortDir: sortDir as never,
            range: range as never,
          },
        )
      return res.data
    },
  })

  const columns: TableProps<VariantAggregateRow>['columns'] = [
    { title: '变体', dataIndex: 'variant_name', key: 'variant_name', ellipsis: true },
    { title: '公式', dataIndex: 'formula_name', key: 'formula_name' },
    {
      title: 'GMV',
      dataIndex: 'gmv',
      key: 'gmv',
      sorter: true,
      render: fmtMoney,
    },
    {
      title: '订单',
      dataIndex: 'orders',
      key: 'orders',
      sorter: true,
    },
    {
      title: '加购',
      dataIndex: 'cart_clicks',
      key: 'cart_clicks',
      sorter: true,
    },
    {
      title: '完播率',
      dataIndex: 'completion_rate_full',
      key: 'completion_rate_full',
      sorter: true,
      render: fmtRate,
    },
    {
      title: '加购率',
      dataIndex: 'cart_rate',
      key: 'cart_rate',
      sorter: true,
      render: fmtRate,
    },
  ]

  return (
    <Card size="small" data-testid="variant-comparison-table">
      <Table<VariantAggregateRow>
        size="small"
        rowKey="variant_id"
        loading={isLoading}
        columns={columns}
        dataSource={data?.items ?? []}
        pagination={{
          current: page,
          pageSize,
          total: data?.total ?? 0,
          showSizeChanger: true,
          onChange: (p, s) => {
            setPage(p)
            setPageSize(s)
          },
        }}
        onChange={(_pagination, _filters, sorter) => {
          if (sorter && !Array.isArray(sorter) && sorter.columnKey && sorter.order) {
            setSortBy(sorter.columnKey as SortBy)
            setSortDir(sorter.order === 'ascend' ? 'asc' : 'desc')
          }
        }}
      />
    </Card>
  )
}
