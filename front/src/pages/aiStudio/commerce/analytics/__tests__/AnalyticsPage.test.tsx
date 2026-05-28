/**
 * AnalyticsPage 单测（W22-T3，P4 Wave B 2/11）。
 *
 * 覆盖：
 * 1. 4 张 chart 卡片全渲染（公式 / 钩子 / 人格 / 平台）。
 * 2. metric 切换（gmv → cart_clicks）后所有 4 个 service 重新以新指标调用。
 * 3. 单个 service 抛错时仅对应卡片显示 Alert，其它卡片正常。
 * 4. 顶部 Segmented metric 选择器存在并显示默认 GMV。
 *
 * Mock 方式：
 * - vi.mock 替换 @ant-design/charts 防止 G2/canvas 在 jsdom 中崩溃。
 * - vi.spyOn 接管 4 个 generated service 方法。
 */
import React from 'react'
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

void React

beforeAll(() => {
  if (!window.matchMedia) {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: (query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }),
    })
  }
  if (!(globalThis as unknown as { ResizeObserver?: unknown }).ResizeObserver) {
    ;(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  }
})

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

import { CommerceAnalyticsService } from '../../../../../services/generated'
import { AnalyticsPage } from '../AnalyticsPage'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let formulaSpy: any
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let hookSpy: any
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let archetypeSpy: any
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let platformSpy: any

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
}

function renderPage() {
  const client = makeClient()
  return render(
    <QueryClientProvider client={client}>
      <AnalyticsPage />
    </QueryClientProvider>,
  )
}

function makeResponse(
  dimension: string,
  points: { dimension_id: string; dimension_name: string; metric_value: number }[],
) {
  return { data: { dimension, metric: 'gmv', points } }
}

describe('AnalyticsPage', () => {
  beforeEach(() => {
    formulaSpy = vi
      .spyOn(CommerceAnalyticsService, 'getAnalyticsByFormulaApiV1CommerceAnalyticsByFormulaGet')
      .mockResolvedValue(
        makeResponse('formula', [
          { dimension_id: 'f_underdog', dimension_name: '凡人逆袭', metric_value: 3300 },
        ]) as unknown as Awaited<ReturnType<
          typeof CommerceAnalyticsService.getAnalyticsByFormulaApiV1CommerceAnalyticsByFormulaGet>
        >,
      )
    hookSpy = vi
      .spyOn(CommerceAnalyticsService, 'getAnalyticsByHookApiV1CommerceAnalyticsByHookGet')
      .mockResolvedValue(
        makeResponse('hook', [
          { dimension_id: 'h_question', dimension_name: '问句钩子', metric_value: 3000 },
        ]) as unknown as Awaited<ReturnType<
          typeof CommerceAnalyticsService.getAnalyticsByHookApiV1CommerceAnalyticsByHookGet>
        >,
      )
    archetypeSpy = vi
      .spyOn(
        CommerceAnalyticsService,
        'getAnalyticsByArchetypeApiV1CommerceAnalyticsByArchetypeGet',
      )
      .mockResolvedValue(
        makeResponse('archetype', [
          { dimension_id: 'sage', dimension_name: '智者', metric_value: 1500 },
        ]) as unknown as Awaited<ReturnType<
          typeof CommerceAnalyticsService.getAnalyticsByArchetypeApiV1CommerceAnalyticsByArchetypeGet>
        >,
      )
    platformSpy = vi
      .spyOn(CommerceAnalyticsService, 'getAnalyticsByPlatformApiV1CommerceAnalyticsByPlatformGet')
      .mockResolvedValue(
        makeResponse('platform', [
          { dimension_id: 'douyin', dimension_name: 'douyin', metric_value: 1500 },
        ]) as unknown as Awaited<ReturnType<
          typeof CommerceAnalyticsService.getAnalyticsByPlatformApiV1CommerceAnalyticsByPlatformGet>
        >,
      )
  })

  afterEach(() => {
    formulaSpy.mockRestore()
    hookSpy.mockRestore()
    archetypeSpy.mockRestore()
    platformSpy.mockRestore()
  })

  it('case 1: 4 张 chart 卡片全渲染（公式 / 钩子 / 人格 / 平台）', async () => {
    renderPage()

    await waitFor(() => {
      expect(formulaSpy).toHaveBeenCalled()
      expect(hookSpy).toHaveBeenCalled()
      expect(archetypeSpy).toHaveBeenCalled()
      expect(platformSpy).toHaveBeenCalled()
    })

    expect(screen.getByTestId('chart-by-formula')).toBeInTheDocument()
    expect(screen.getByTestId('chart-by-hook')).toBeInTheDocument()
    expect(screen.getByTestId('chart-by-archetype')).toBeInTheDocument()
    expect(screen.getByTestId('chart-by-platform')).toBeInTheDocument()
  })

  it('case 2: metric 切换（gmv → cart_clicks）后所有 4 个 service 重新以新指标调用', async () => {
    renderPage()

    await waitFor(() => {
      expect(formulaSpy).toHaveBeenCalledTimes(1)
    })
    expect(formulaSpy).toHaveBeenLastCalledWith(expect.objectContaining({ metric: 'gmv' }))

    const cartBtn = screen.getByText('加购点击')
    fireEvent.click(cartBtn)

    await waitFor(() => {
      expect(formulaSpy).toHaveBeenCalledTimes(2)
      expect(hookSpy).toHaveBeenCalledTimes(2)
      expect(archetypeSpy).toHaveBeenCalledTimes(2)
      expect(platformSpy).toHaveBeenCalledTimes(2)
    })
    expect(formulaSpy).toHaveBeenLastCalledWith(expect.objectContaining({ metric: 'cart_clicks' }))
    expect(platformSpy).toHaveBeenLastCalledWith(expect.objectContaining({ metric: 'cart_clicks' }))
  })

  it('case 3: 单个 service 抛错时仅对应卡片显示 Alert，其它卡片仍正常渲染数据', async () => {
    formulaSpy.mockRejectedValueOnce(new Error('boom-formula'))

    renderPage()

    await waitFor(() => {
      expect(screen.getAllByRole('alert').length).toBeGreaterThan(0)
    })

    const formulaCard = screen.getByTestId('chart-by-formula')
    expect(formulaCard.textContent ?? '').toMatch(/加载失败|boom-formula/)

    const otherCharts = [
      screen.getByTestId('chart-by-hook'),
      screen.getByTestId('chart-by-archetype'),
      screen.getByTestId('chart-by-platform'),
    ]
    otherCharts.forEach((card) => {
      expect(card.textContent ?? '').not.toMatch(/加载失败/)
    })
  })

  it('case 4: 顶部 Segmented metric 选择器存在并显示默认 GMV', () => {
    renderPage()
    expect(document.querySelector('.ant-segmented')).toBeInTheDocument()
    expect(screen.getAllByText('GMV').length).toBeGreaterThanOrEqual(1)
  })
})
