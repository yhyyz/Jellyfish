/**
 * ConsistencyReviewDrawer 单测（W27-T3 TDD）。
 *
 * 覆盖契约：
 *
 * 1. ``test_drawer_loads_sampled_frames_and_reference``：抽屉打开时调用
 *    OpenAPI generated client，渲染抽样帧 + 参考图。
 * 2. retry_count > 0 时显示 "已重试 N 次" 标签；为 null/0 时不渲染。
 * 3. shotId=null 时直接走 Empty 分支，不发起请求。
 *
 * 测试策略：
 * - 通过 ``vi.spyOn`` 拦截
 *   ``CommerceShotConsistencyService.getShotConsistencyEvidence...``，
 *   返回固定 fixture，避免真实网络。
 * - antd Drawer / Image 在 jsdom 缺少 matchMedia / ResizeObserver / Image
 *   等 API，按 ``BrandStyleGuideForm.test.tsx`` 同款 polyfill 兜底。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach, beforeAll } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import {
  CommerceShotConsistencyService,
  type ConsistencyEvidenceRead,
} from '../../../../../../services/generated'
import { ConsistencyReviewDrawer } from '../ConsistencyReviewDrawer'

// jsdom 下 antd Drawer / Tooltip / Image 触摸 matchMedia & ResizeObserver；
// 与 BrandStyleGuideForm.test.tsx 同款兜底（按 task 要求保留 beforeAll）。
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

// MockInstance 与 spy 的实际签名存在 TS 噪音，用 any 别名规避。
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let mockedGet: any

/** 干净 QueryClient，关闭 retry 避免 RED 用例被自动重试拖时间。 */
function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
}

function renderWithClient(ui: React.ReactNode) {
  return render(<QueryClientProvider client={makeClient()}>{ui}</QueryClientProvider>)
}

/** 构造 ConsistencyEvidenceRead fixture。 */
function makeEvidence(
  overrides: Partial<ConsistencyEvidenceRead> = {},
): ConsistencyEvidenceRead {
  return {
    shot_id: 'shot-1',
    score: 0.91,
    status: 'green',
    sampled_frame_urls: [
      'http://example.com/sample-1.jpg',
      'http://example.com/sample-2.jpg',
    ],
    reference_image_url: 'http://example.com/reference.jpg',
    reference_view_angle: 'FRONT',
    retry_count: null,
    ...overrides,
  }
}

describe('ConsistencyReviewDrawer', () => {
  beforeEach(() => {
    mockedGet = vi.spyOn(
      CommerceShotConsistencyService,
      'getShotConsistencyEvidenceApiV1CommerceShotsShotIdConsistencyEvidenceGet',
    )
  })

  afterEach(() => {
    mockedGet.mockRestore()
  })

  it('test_drawer_loads_sampled_frames_and_reference: 加载抽样帧 + 参考图', async () => {
    mockedGet.mockResolvedValue({ data: makeEvidence() })

    renderWithClient(
      <ConsistencyReviewDrawer open onClose={() => {}} shotId="shot-1" />,
    )

    // 等待 drawer 内容渲染
    await waitFor(() => {
      expect(screen.getByTestId('consistency-summary')).toBeInTheDocument()
    })

    // PreviewGroup 容器存在
    expect(screen.getByTestId('consistency-preview-strip')).toBeInTheDocument()

    // 抽样帧 + 参考图都被渲染（共 3 张：2 sample + 1 reference）
    const images = document.querySelectorAll('img')
    expect(images.length).toBeGreaterThanOrEqual(3)

    // 至少有一张图片 src 是参考图
    const srcs = Array.from(images).map((img) => img.getAttribute('src') ?? '')
    expect(srcs).toContain('http://example.com/reference.jpg')
    expect(srcs).toContain('http://example.com/sample-1.jpg')

    // mock 被调用一次
    expect(mockedGet).toHaveBeenCalledTimes(1)
    expect(mockedGet).toHaveBeenCalledWith({ shotId: 'shot-1' })
  })

  it('retry_count > 0 时渲染 "已重试 N 次" 标签', async () => {
    mockedGet.mockResolvedValue({
      data: makeEvidence({ retry_count: 2 }),
    })

    renderWithClient(
      <ConsistencyReviewDrawer open onClose={() => {}} shotId="shot-1" />,
    )

    await waitFor(() => {
      expect(screen.getByTestId('retry-count-tag')).toBeInTheDocument()
    })
    expect(screen.getByTestId('retry-count-tag').textContent).toContain('已重试 2 次')
  })

  it('retry_count = null 时不渲染重试标签', async () => {
    mockedGet.mockResolvedValue({
      data: makeEvidence({ retry_count: null }),
    })

    renderWithClient(
      <ConsistencyReviewDrawer open onClose={() => {}} shotId="shot-1" />,
    )

    await waitFor(() => {
      expect(screen.getByTestId('consistency-summary')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('retry-count-tag')).toBeNull()
  })

  it('shotId=null 时不发起请求，渲染 Empty 占位', async () => {
    renderWithClient(
      <ConsistencyReviewDrawer open onClose={() => {}} shotId={null} />,
    )

    // 等一拍确保异步 query 不会被触发
    await new Promise((r) => setTimeout(r, 30))

    expect(mockedGet).not.toHaveBeenCalled()
    // antd Empty 默认 description "暂无数据" / 自定义 "未提供镜头 ID"
    expect(screen.getByText(/未提供镜头 ID/)).toBeInTheDocument()
  })
})
