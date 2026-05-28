/**
 * PerformanceChart 单测（W22-T3，P4 Wave B 2/11）。
 *
 * 因 antd-charts v2 内部使用 G2/canvas（jsdom 不支持），通过 vi.mock 替换
 * `@ant-design/charts`，仅以占位 div 验证 PerformanceChart 自己的分支
 * 逻辑（loading / error / empty / column / line / pie）。
 */
import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

void React

vi.mock('@ant-design/charts', () => ({
  Column: ({ data }: { data: unknown[] }) => (
    <div data-testid="mock-column">column:{(data ?? []).length}</div>
  ),
  Line: ({ data }: { data: unknown[] }) => (
    <div data-testid="mock-line">line:{(data ?? []).length}</div>
  ),
  Pie: ({ data }: { data: unknown[] }) => (
    <div data-testid="mock-pie">pie:{(data ?? []).length}</div>
  ),
}))

import { PerformanceChart } from '../PerformanceChart'
import type { ChartDataPoint } from '../../../services/generated'

function makePoints(): ChartDataPoint[] {
  return [
    { dimension_id: 'a', dimension_name: '凡人逆袭', metric_value: 1000 },
    { dimension_id: 'b', dimension_name: '对比反差', metric_value: 500 },
  ]
}

describe('PerformanceChart', () => {
  it('case 1: column 形态渲染对应数量的数据点容器', () => {
    render(
      <PerformanceChart data={makePoints()} dimension="formula" metric="gmv" chartType="column" />,
    )
    expect(screen.getByTestId('mock-column')).toHaveTextContent('column:2')
    expect(screen.getByLabelText('formula-gmv-column')).toBeInTheDocument()
  })

  it('case 2: empty 态：data=[] 时渲染 Empty 占位且不渲染 column', () => {
    render(<PerformanceChart data={[]} dimension="hook" metric="orders" chartType="column" />)
    expect(screen.queryByTestId('mock-column')).toBeNull()
    expect(screen.getByText(/暂无 hook 维度的 orders 数据/)).toBeInTheDocument()
  })

  it('case 3: error 态显示 Alert 与重试按钮，点击触发 onRetry', () => {
    const onRetry = vi.fn()
    render(
      <PerformanceChart
        data={[]}
        dimension="archetype"
        metric="cart_clicks"
        error={new Error('boom')}
        onRetry={onRetry}
      />,
    )
    const retry = screen.getByRole('button', { name: /重\s*试/ })
    fireEvent.click(retry)
    expect(onRetry).toHaveBeenCalledTimes(1)
    expect(screen.queryByTestId('mock-column')).toBeNull()
  })

  it('case 4: loading 态渲染 Skeleton，不渲染图表', () => {
    render(
      <PerformanceChart data={makePoints()} dimension="formula" metric="gmv" loading={true} />,
    )
    expect(screen.queryByTestId('mock-column')).toBeNull()
    expect(document.querySelector('.ant-skeleton')).toBeInTheDocument()
  })

  it('case 5: chartType=pie 渲染 Pie 容器，metric 切换更新 aria', () => {
    const { rerender } = render(
      <PerformanceChart data={makePoints()} dimension="archetype" metric="gmv" chartType="pie" />,
    )
    expect(screen.getByTestId('mock-pie')).toHaveTextContent('pie:2')
    expect(screen.getByLabelText('archetype-gmv-pie')).toBeInTheDocument()

    rerender(
      <PerformanceChart
        data={makePoints()}
        dimension="archetype"
        metric="completion_rate_full"
        chartType="pie"
      />,
    )
    expect(screen.getByLabelText('archetype-completion_rate_full-pie')).toBeInTheDocument()
  })

  it('case 6: chartType=line 渲染 Line 容器', () => {
    render(
      <PerformanceChart
        data={makePoints()}
        dimension="platform"
        metric="orders"
        chartType="line"
      />,
    )
    expect(screen.getByTestId('mock-line')).toHaveTextContent('line:2')
    expect(screen.getByLabelText('platform-orders-line')).toBeInTheDocument()
  })
})
