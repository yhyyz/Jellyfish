/**
 * HookPatternSelector 组件 TDD 测试套件（W13 backfill）。
 *
 * P2 钩子模式选择器是 StoryWorkbench 的关键决策入口；W11 中已实装但
 * 缺失契约级测试，本文件按 W12 backfill 模式补齐 ≥3 条核心契约：
 *
 * 1. 拉到钩子列表后逐条渲染（覆盖 name + pattern_type + description）。
 * 2. 单击列表项触发 `onChange(id)` 一次，参数为该行的钩子 ID。
 * 3. 后端返回空列表时显示「暂无可用钩子」空态文案，且不会爆错。
 *
 * 测试基础设施：
 * - 与 BrandStyleGuideForm.test.tsx 保持一致：在 beforeAll 内补
 *   `matchMedia` + `ResizeObserver` 兜底，避免 antd Card / Select / List
 *   在 jsdom 下访问未实现的浏览器 API 时崩溃。
 * - 关闭 retry 的 QueryClient，避免 reject 路径被自动重试拖累。
 */
import React from 'react'
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import {
  StudioHookPatternsService,
  type HookPatternRead,
} from '../../../../../../services/generated'
import { HookPatternSelector } from '../HookPatternSelector'

// 与 BrandStyleGuideForm.test.tsx 保持同样的 antd polyfill 兜底：
// jsdom 默认不实现 matchMedia / ResizeObserver，antd 的 Card / List /
// Select 在挂载时会触摸这两个 API，缺失时直接 throw。
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

// vitest 2.x 的 MockInstance 泛型对静态类成员 spy 不友好（TS2344），
// 与 VoicePackPicker.test.tsx 保持一致用 any 别名。
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let mockedList: any

/**
 * 构造一条 HookPatternRead fixture，便于覆写局部字段。
 */
function makeHook(overrides: Partial<HookPatternRead> = {}): HookPatternRead {
  return {
    id: 'question_hook',
    name: '问句钩子',
    pattern_type: 'question',
    description: '通过提问引发好奇',
    template_text: '你知道{topic}吗？',
    psychology: '问句激活大脑搜索机制，提升观看时长',
    use_cases: ['知识科普'],
    avoid_cases: ['强情节短剧'],
    is_system: true,
    sort_order: 0,
    created_at: '2026-05-28T00:00:00Z',
    ...overrides,
  }
}

/**
 * 干净 QueryClient：关闭 retry，避免 reject 用例被自动重试。
 */
function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
}

/**
 * QueryClientProvider 包裹后渲染。
 */
function renderWithClient(ui: React.ReactNode, client: QueryClient = makeClient()) {
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('HookPatternSelector', () => {
  beforeEach(() => {
    mockedList = vi.spyOn(
      StudioHookPatternsService,
      'listHookPatternsApiV1StudioHookPatternsGet',
    )
  })

  afterEach(() => {
    mockedList.mockRestore()
  })

  it('case 1: 渲染钩子列表，name / pattern_type / description 同时可见', async () => {
    mockedList.mockResolvedValue({
      data: [
        makeHook({
          id: 'question_hook',
          name: '问句钩子',
          pattern_type: 'question',
          description: '通过提问引发好奇',
        }),
        makeHook({
          id: 'shock_hook',
          name: '震惊钩子',
          pattern_type: 'shock',
          description: '反常识开场',
        }),
      ],
    })

    renderWithClient(<HookPatternSelector selectedId={null} onChange={() => {}} />)

    expect(await screen.findByText('问句钩子')).toBeInTheDocument()
    expect(screen.getByText('震惊钩子')).toBeInTheDocument()
    // pattern_type 作为 Tag 渲染在每行右侧
    expect(screen.getByText('question')).toBeInTheDocument()
    expect(screen.getByText('shock')).toBeInTheDocument()
    // description 作为副标题
    expect(screen.getByText('通过提问引发好奇')).toBeInTheDocument()
  })

  it('case 2: 单击列表项触发 onChange，参数为该行的钩子 ID', async () => {
    mockedList.mockResolvedValue({
      data: [
        makeHook({ id: 'question_hook', name: '问句钩子' }),
        makeHook({
          id: 'conflict_hook',
          name: '冲突钩子',
          pattern_type: 'conflict',
        }),
      ],
    })

    const onChange = vi.fn()
    renderWithClient(<HookPatternSelector selectedId={null} onChange={onChange} />)

    const row = await screen.findByText('冲突钩子')
    fireEvent.click(row)

    await waitFor(() => {
      expect(onChange).toHaveBeenCalledTimes(1)
    })
    expect(onChange).toHaveBeenCalledWith('conflict_hook')
  })

  it('case 3: 后端返回空数组时显示「暂无可用钩子」空态', async () => {
    mockedList.mockResolvedValue({ data: [] })

    renderWithClient(<HookPatternSelector selectedId={null} onChange={() => {}} />)

    expect(await screen.findByText('暂无可用钩子')).toBeInTheDocument()
  })
})
