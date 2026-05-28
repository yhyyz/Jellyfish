/**
 * FormulaLibrary 页面 TDD 测试套件（W13 backfill）。
 *
 * P2 公式库为只读浏览面板，含 12 条系统级剧情公式（6 cn + 6 global）。
 * 本文件按 W12 backfill 模式补齐 ≥3 条核心契约：
 *
 * 1. 默认渲染公式表格，覆盖 name / region / category / typical_duration_sec。
 * 2. 点击「查看详情」按钮触发 GET /story-formulas/{id}，并在 Drawer 内
 *    展示 FormulaDetailView 的关键字段。
 * 3. 后端返回空数组时表格显示「暂无公式」空态文案。
 *
 * 测试基础设施：
 * - 与 BrandStyleGuideForm.test.tsx 保持一致：补 matchMedia +
 *   ResizeObserver；antd Table / Drawer / Spin 都需要这两个 API。
 */
import React from 'react'
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import {
  StudioStoryFormulasService,
  type StoryFormulaRead,
} from '../../../../../services/generated'
import FormulaLibrary from '../FormulaLibrary'

// antd matchMedia / ResizeObserver 兜底。
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

// 静态成员 spy 别名（vitest 2.x MockInstance 泛型限制）。
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let mockedList: any
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let mockedDetail: any

/**
 * 构造 StoryFormulaRead fixture。
 */
function makeFormula(overrides: Partial<StoryFormulaRead> = {}): StoryFormulaRead {
  return {
    id: 'underdog_triumph',
    name: '凡人逆袭',
    region: 'cn',
    category: 'transformation',
    structure: {
      beats: [
        {
          id: 'setup',
          duration_sec: 5,
          function: '建立平凡日常',
          shot_type: '全景',
          recommended_camera_movement: 'static',
        },
        {
          id: 'rise',
          duration_sec: 8,
          function: '主角崛起',
          shot_type: '中景',
          recommended_camera_movement: 'pan',
        },
      ],
      total_shots_range: [4, 6],
      duration_sec_range: [12, 18],
    },
    risk_flags: ['夸大效果'],
    sample_dialog: '当所有人都看不起我时…',
    typical_duration_sec: 15,
    typical_shot_count: 5,
    psychology: '观众投射「我也能做到」的自我认同',
    use_cases: ['美妆产品转变'],
    avoid_cases: ['极端情绪化场景'],
    prompt_template_id: 'tpl_underdog_triumph',
    is_system: true,
    sort_order: 0,
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

describe('FormulaLibrary', () => {
  beforeEach(() => {
    mockedList = vi.spyOn(
      StudioStoryFormulasService,
      'listStoryFormulasApiV1StudioStoryFormulasGet',
    )
    mockedDetail = vi.spyOn(
      StudioStoryFormulasService,
      'getStoryFormulaApiV1StudioStoryFormulasFormulaIdGet',
    )
  })

  afterEach(() => {
    mockedList.mockRestore()
    mockedDetail.mockRestore()
  })

  it('case 1: 默认渲染公式表格，name / region / category / 时长 同时可见', async () => {
    mockedList.mockResolvedValue({
      data: [
        makeFormula({
          id: 'underdog_triumph',
          name: '凡人逆袭',
          region: 'cn',
          category: 'transformation',
          typical_duration_sec: 15,
          typical_shot_count: 5,
        }),
        makeFormula({
          id: 'hero_journey',
          name: '英雄之旅',
          region: 'global',
          category: 'classic',
          typical_duration_sec: 30,
          typical_shot_count: 8,
        }),
      ],
    })

    renderWithClient(<FormulaLibrary />)

    expect(await screen.findByText('凡人逆袭')).toBeInTheDocument()
    expect(screen.getByText('英雄之旅')).toBeInTheDocument()
    // region 标签（小写直接渲染）
    expect(screen.getByText('cn')).toBeInTheDocument()
    expect(screen.getByText('global')).toBeInTheDocument()
    // category 列
    expect(screen.getByText('transformation')).toBeInTheDocument()
    expect(screen.getByText('classic')).toBeInTheDocument()
    // 时长列（s 后缀）
    expect(screen.getByText('15s')).toBeInTheDocument()
    expect(screen.getByText('30s')).toBeInTheDocument()
  })

  it('case 2: 点击「查看详情」打开 Drawer 并加载详情数据', async () => {
    const formula = makeFormula({
      id: 'underdog_triumph',
      name: '凡人逆袭',
      region: 'cn',
      category: 'transformation',
      psychology: '观众投射「我也能做到」的自我认同',
    })
    mockedList.mockResolvedValue({ data: [formula] })
    mockedDetail.mockResolvedValue({ data: formula })

    renderWithClient(<FormulaLibrary />)

    await screen.findByText('凡人逆袭')

    const detailBtn = screen.getByRole('button', { name: '查看详情' })
    fireEvent.click(detailBtn)

    // 详情接口被调用
    await waitFor(() => {
      expect(mockedDetail).toHaveBeenCalledTimes(1)
    })
    expect(mockedDetail).toHaveBeenCalledWith({
      formulaId: 'underdog_triumph',
    })

    // Drawer 内出现 FormulaDetailView 的标志性段落（心理学原理 Card 标题）
    expect(await screen.findByText('心理学原理')).toBeInTheDocument()
    // 心理学正文也应渲染
    expect(
      await screen.findByText('观众投射「我也能做到」的自我认同'),
    ).toBeInTheDocument()
  })

  it('case 3: 后端返回空数组时显示「暂无公式」空态', async () => {
    mockedList.mockResolvedValue({ data: [] })

    renderWithClient(<FormulaLibrary />)

    expect(await screen.findByText('暂无公式')).toBeInTheDocument()
    // 详情接口不应被调用
    expect(mockedDetail).not.toHaveBeenCalled()
  })
})
