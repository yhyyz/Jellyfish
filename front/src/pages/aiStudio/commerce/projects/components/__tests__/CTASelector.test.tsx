/**
 * CTASelector 组件 TDD 测试套件（W13 backfill）。
 *
 * P2 CTA 选择器是 StoryWorkbench 的"行动召唤"决策入口；与
 * HookPatternSelector 不同，它走 hardness × urgency_type 双轴过滤。
 * 本文件按 W12 backfill 模式补齐 ≥3 条核心契约：
 *
 * 1. 拉到 CTA 列表后逐条渲染（覆盖 name + hardness + urgency_type）。
 * 2. 单击列表项触发 `onChange(id)` 一次，参数为该行的 CTA ID。
 * 3. 后端返回空列表时显示「暂无可用 CTA」空态文案。
 *
 * 测试基础设施：
 * - 与 BrandStyleGuideForm.test.tsx 保持一致：补 `matchMedia` +
 *   `ResizeObserver` 兜底。
 * - 关闭 retry 的 QueryClient，避免 reject 路径被自动重试。
 */
import React from 'react'
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import {
  StudioCtaPatternsService,
  type CtaPatternRead,
} from '../../../../../../services/generated'
import { CTASelector } from '../CTASelector'

// antd matchMedia / ResizeObserver 兜底（同 BrandStyleGuideForm.test.tsx）。
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

// 与 VoicePackPicker.test.tsx 保持一致用 any 别名（vitest 2.x MockInstance 泛型限制）。
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let mockedList: any

/**
 * 构造 CtaPatternRead fixture。
 */
function makeCta(overrides: Partial<CtaPatternRead> = {}): CtaPatternRead {
  return {
    id: 'scarcity_cta',
    name: '稀缺紧迫',
    hardness: 'hard',
    urgency_type: 'scarcity',
    description: '强调库存稀缺',
    template_text: '仅剩{count}件',
    sample_phrases: ['仅剩 100 件'],
    is_system: true,
    sort_order: 0,
    created_at: '2026-05-28T00:00:00Z',
    ...overrides,
  }
}

/**
 * 关闭 retry 的 QueryClient。
 */
function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
}

/**
 * QueryClientProvider 包裹渲染。
 */
function renderWithClient(ui: React.ReactNode, client: QueryClient = makeClient()) {
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('CTASelector', () => {
  beforeEach(() => {
    mockedList = vi.spyOn(
      StudioCtaPatternsService,
      'listCtaPatternsApiV1StudioCtaPatternsGet',
    )
  })

  afterEach(() => {
    mockedList.mockRestore()
  })

  it('case 1: 渲染 CTA 列表，name / hardness / urgency_type 三 Tag 同时可见', async () => {
    mockedList.mockResolvedValue({
      data: [
        makeCta({
          id: 'scarcity_cta',
          name: '稀缺紧迫',
          hardness: 'hard',
          urgency_type: 'scarcity',
        }),
        makeCta({
          id: 'social_proof_cta',
          name: '社会证明',
          hardness: 'soft',
          urgency_type: 'social_proof',
        }),
      ],
    })

    renderWithClient(<CTASelector selectedId={null} onChange={() => {}} />)

    expect(await screen.findByText('稀缺紧迫')).toBeInTheDocument()
    expect(screen.getByText('社会证明')).toBeInTheDocument()
    // 双轴 Tag：hardness + urgency_type 同时渲染
    expect(screen.getByText('hard')).toBeInTheDocument()
    expect(screen.getByText('scarcity')).toBeInTheDocument()
    expect(screen.getByText('soft')).toBeInTheDocument()
    expect(screen.getByText('social_proof')).toBeInTheDocument()
  })

  it('case 2: 单击列表项触发 onChange(id) 一次', async () => {
    mockedList.mockResolvedValue({
      data: [
        makeCta({ id: 'scarcity_cta', name: '稀缺紧迫' }),
        makeCta({
          id: 'benefit_cta',
          name: '利益驱动',
          hardness: 'medium',
          urgency_type: 'benefit',
        }),
      ],
    })

    const onChange = vi.fn()
    renderWithClient(<CTASelector selectedId={null} onChange={onChange} />)

    const row = await screen.findByText('利益驱动')
    fireEvent.click(row)

    await waitFor(() => {
      expect(onChange).toHaveBeenCalledTimes(1)
    })
    expect(onChange).toHaveBeenCalledWith('benefit_cta')
  })

  it('case 3: 后端返回空数组时显示「暂无可用 CTA」空态', async () => {
    mockedList.mockResolvedValue({ data: [] })

    renderWithClient(<CTASelector selectedId={null} onChange={() => {}} />)

    expect(await screen.findByText('暂无可用 CTA')).toBeInTheDocument()
  })
})
