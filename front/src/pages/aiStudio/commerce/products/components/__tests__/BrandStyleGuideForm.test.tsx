/**
 * BrandStyleGuideForm 组件 TDD 测试套件（W25-T3）。
 *
 * 覆盖 ≥3 条核心契约：
 *
 * 1. 后端返回 200 + 完整规范时，4 个字段的初始值正确回填到表单；
 * 2. 后端返回 404 BrandStyleGuide（"尚未创建"）时，渲染空态提示；点击「保存」
 *    走 POST upsert 路径并发起 mutation；
 * 3. 已有规范的场景下，点击「清空规范」+ Popconfirm 确认会触发 DELETE
 *    mutation，且参数为当前 productId；
 * 4. 未传 productId 时不会发起任何 GET 请求，UI 进入"未选择商品"空态；
 * 5. 后端返回非 404 错误时显示错误 banner（fail-fast）。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach, beforeAll } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import {
  ApiError,
  StudioBrandStyleGuidesService,
  type BrandStyleGuideRead,
} from '../../../../../../services/generated'
import { BrandStyleGuideForm } from '../BrandStyleGuideForm'

// antd 的 Form / Select / Popconfirm 在 jsdom 中会触摸 matchMedia 与
// ResizeObserver，需在测试启动前补齐；与 SubtitleStylePicker.test.tsx
// 保持同样的兜底 pattern。
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

// 测试中只关心 spy 的 mockResolvedValue / mockRejectedValueOnce API，
// MockInstance 的精确返回类型与 spy 的实际签名存在 TS 噪音，故用 any 别名。
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let mockedGet: any
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let mockedUpsert: any
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let mockedDelete: any

/**
 * 构造 BrandStyleGuideRead fixture，便于覆写局部字段。
 */
function makeGuide(overrides: Partial<BrandStyleGuideRead> = {}): BrandStyleGuideRead {
  return {
    id: 'g_default',
    product_id: 'p1',
    forced_phrases: ['今天买不亏'],
    banned_patterns: ['宇宙第一'],
    required_endings: ['详情见详情页'],
    brand_persona_tagline: '理性消费的成分党',
    created_at: '2026-05-28T00:00:00Z',
    updated_at: '2026-05-28T00:00:00Z',
    ...overrides,
  }
}

/**
 * 构造一个干净的 QueryClient：关闭 retry，避免 404/500 用例被自动 retry 拖时间。
 */
function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
}

/**
 * 用 QueryClientProvider 包裹后渲染。
 */
function renderWithClient(ui: React.ReactNode, client: QueryClient = makeClient()) {
  const utils = render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
  return { ...utils, client }
}

/**
 * 构造一个真实的 ApiError 实例，模拟后端 4xx/5xx 响应。
 */
function buildApiError(statusCode: number, body: unknown = { detail: 'not found' }): ApiError {
  // ApiError 构造期望 (request, response, message) 三元组；测试只关心 status。
  return new ApiError(
    { method: 'GET', url: 'http://test' } as never,
    {
      url: 'http://test',
      ok: false,
      status: statusCode,
      statusText: 'error',
      body,
    } as never,
    `HTTP ${statusCode}`,
  )
}

describe('BrandStyleGuideForm', () => {
  beforeEach(() => {
    mockedGet = vi.spyOn(
      StudioBrandStyleGuidesService,
      'getBrandStyleGuideApiV1StudioProductsProductIdBrandStyleGuideGet',
    )
    mockedUpsert = vi.spyOn(
      StudioBrandStyleGuidesService,
      'upsertBrandStyleGuideApiV1StudioProductsProductIdBrandStyleGuidePost',
    )
    mockedDelete = vi.spyOn(
      StudioBrandStyleGuidesService,
      'deleteBrandStyleGuideApiV1StudioProductsProductIdBrandStyleGuideDelete',
    )
  })

  afterEach(() => {
    mockedGet.mockRestore()
    mockedUpsert.mockRestore()
    mockedDelete.mockRestore()
  })

  it('case 1: 拉到已有规范时，表单字段被正确回填', async () => {
    mockedGet.mockResolvedValue({
      data: makeGuide({
        product_id: 'p1',
        forced_phrases: ['买它', '立享'],
        banned_patterns: ['超神', '永远'],
        required_endings: ['详情请咨询'],
        brand_persona_tagline: '冷静的导购',
      }),
    })

    renderWithClient(<BrandStyleGuideForm productId="p1" />)

    // tagline 文本框内容已回填
    const tagline = await screen.findByPlaceholderText(/理性的成分党闺蜜/)
    expect((tagline as HTMLTextAreaElement).value).toBe('冷静的导购')

    // tag 模式 select 会把每条作为一个 option 渲染（aria-label="买它" 等）
    expect(await screen.findByText('买它')).toBeInTheDocument()
    expect(screen.getByText('立享')).toBeInTheDocument()
    expect(screen.getByText('超神')).toBeInTheDocument()
    expect(screen.getByText('详情请咨询')).toBeInTheDocument()

    // 已有规范时，"清空规范"按钮应可见
    expect(screen.getByTestId('brand-style-guide-delete')).toBeInTheDocument()
  })

  it('case 2: 后端返回 404 BrandStyleGuide 时显示空态提示，保存触发 upsert', async () => {
    mockedGet.mockRejectedValue(buildApiError(404, { detail: 'BrandStyleGuide not found' }))
    mockedUpsert.mockResolvedValue({
      data: makeGuide({ product_id: 'p2' }),
    })

    renderWithClient(<BrandStyleGuideForm productId="p2" />)

    // 等空态提示出现
    expect(
      await screen.findByText(/尚未配置品牌话术规范/),
    ).toBeInTheDocument()

    // 没有规范时，"清空规范"按钮不应渲染
    expect(screen.queryByTestId('brand-style-guide-delete')).not.toBeInTheDocument()

    // 点击保存
    fireEvent.click(screen.getByTestId('brand-style-guide-submit'))

    await waitFor(() => {
      expect(mockedUpsert).toHaveBeenCalledTimes(1)
    })
    expect(mockedUpsert).toHaveBeenCalledWith(
      expect.objectContaining({
        productId: 'p2',
        requestBody: expect.objectContaining({
          forced_phrases: [],
          banned_patterns: [],
          required_endings: [],
          brand_persona_tagline: '',
        }),
      }),
    )
  })

  it('case 3: 已有规范时点击清空 + 确认 → DELETE 被调用，参数为当前 productId', async () => {
    mockedGet.mockResolvedValue({
      data: makeGuide({ product_id: 'p3' }),
    })
    mockedDelete.mockResolvedValue(undefined)

    renderWithClient(<BrandStyleGuideForm productId="p3" />)

    // 等清空按钮渲染（说明数据已加载）
    const deleteBtn = await screen.findByTestId('brand-style-guide-delete')
    fireEvent.click(deleteBtn)

    // antd Popconfirm 确认按钮文案是「确认清空」（与组件内 okText 对齐，
    // 与触发按钮「清空规范」相区分）。
    const confirmBtn = await screen.findByRole('button', { name: '确认清空' })
    fireEvent.click(confirmBtn)

    await waitFor(() => {
      expect(mockedDelete).toHaveBeenCalledTimes(1)
    })
    expect(mockedDelete).toHaveBeenCalledWith({ productId: 'p3' })
  })

  it('case 4: 未传 productId 时不会发起 GET，UI 显示"未选择商品"空态', () => {
    renderWithClient(<BrandStyleGuideForm productId={null} />)

    expect(screen.getByTestId('brand-style-guide-empty-product')).toBeInTheDocument()
    expect(mockedGet).not.toHaveBeenCalled()
  })

  it('case 5: 后端返回非 404 错误时显示错误 banner', async () => {
    mockedGet.mockRejectedValue(buildApiError(500, { detail: 'server boom' }))

    renderWithClient(<BrandStyleGuideForm productId="p_err" />)

    expect(
      await screen.findByTestId('brand-style-guide-error'),
    ).toBeInTheDocument()
  })
})
