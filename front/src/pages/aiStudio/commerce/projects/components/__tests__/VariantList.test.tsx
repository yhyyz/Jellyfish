/**
 * VariantList 组件 TDD 测试套件（W13 backfill）。
 *
 * P2 变体列表是 StoryWorkbench 左栏的核心入口；提供选择 / 克隆 /
 * 标记冠军 三类一级操作。本文件按 W12 backfill 模式补齐 ≥3 条核心契约：
 *
 * 1. 渲染变体列表，覆盖 id 摘要 / status Tag / is_champion 高亮。
 * 2. 单击列表项触发 onSelect(id)，参数为该行的 variant ID（点击操作
 *    按钮不会冒泡触发 onSelect）。
 * 3. 点击「标记为冠军」按钮调用 PATCH /story-variants/{id}/champion；
 *    `is_champion=true` 的行该按钮 disabled。
 *
 * 测试基础设施：
 * - 与 BrandStyleGuideForm.test.tsx 保持一致：补 matchMedia +
 *   ResizeObserver；antd List / Modal / message 都需要这两个 API。
 */
import React from 'react'
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import {
  StudioStoryVariantsService,
  type StoryVariantRead,
} from '../../../../../../services/generated'
import { VariantList } from '../VariantList'

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
let mockedChampion: any

/**
 * 构造 StoryVariantRead fixture。
 */
function makeVariant(overrides: Partial<StoryVariantRead> = {}): StoryVariantRead {
  return {
    id: '11111111-aaaa-bbbb-cccc-000000000001',
    project_id: 'p1',
    chapter_id: 'c1',
    formula_id: 'underdog_triumph',
    hook_pattern_id: null,
    cta_pattern_id: null,
    archetype: 'sage',
    script_full_text: '示例剧本',
    script_breakdown: {},
    status: 'ready',
    is_champion: false,
    compliance_score: 90,
    generated_by_task_id: null,
    created_at: '2026-05-28T00:00:00Z',
    updated_at: '2026-05-28T00:00:00Z',
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

describe('VariantList', () => {
  beforeEach(() => {
    mockedChampion = vi.spyOn(
      StudioStoryVariantsService,
      'markVariantChampionApiV1StudioStoryVariantsVariantIdChampionPatch',
    )
  })

  afterEach(() => {
    mockedChampion.mockRestore()
  })

  it('case 1: 渲染变体列表，id 摘要 / status / Champion 标签同时可见', () => {
    const variants = [
      makeVariant({
        id: '11111111-aaaa-bbbb-cccc-000000000001',
        status: 'ready',
        is_champion: true,
        archetype: 'sage',
        compliance_score: 95,
      }),
      makeVariant({
        id: '22222222-aaaa-bbbb-cccc-000000000002',
        status: 'failed',
        is_champion: false,
        archetype: 'jester',
        compliance_score: 60,
      }),
    ]

    renderWithClient(
      <VariantList
        variants={variants}
        activeVariantId={null}
        onSelect={() => {}}
      />,
    )

    // id 前 8 位摘要
    expect(screen.getByText('11111111')).toBeInTheDocument()
    expect(screen.getByText('22222222')).toBeInTheDocument()
    // status Tag 文案
    expect(screen.getByText('ready')).toBeInTheDocument()
    expect(screen.getByText('failed')).toBeInTheDocument()
    // is_champion=true 时显示 Champion 标签
    expect(screen.getByText('Champion')).toBeInTheDocument()
    // 合规分摘要
    expect(screen.getByText('合规 95')).toBeInTheDocument()
    expect(screen.getByText('合规 60')).toBeInTheDocument()
  })

  it('case 2: 单击列表项触发 onSelect(id)，但点击操作按钮不冒泡', async () => {
    const variants = [
      makeVariant({
        id: '11111111-aaaa-bbbb-cccc-000000000001',
        status: 'ready',
        is_champion: false,
      }),
    ]
    const onSelect = vi.fn()

    renderWithClient(
      <VariantList
        variants={variants}
        activeVariantId={null}
        onSelect={onSelect}
      />,
    )

    // 点击列表项主体（id 摘要文字所在区域），应触发 onSelect
    fireEvent.click(screen.getByText('11111111'))
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect).toHaveBeenCalledWith('11111111-aaaa-bbbb-cccc-000000000001')

    // 点击"克隆"按钮：应阻止冒泡 → onSelect 不再增加调用
    onSelect.mockClear()
    const buttons = screen.getAllByRole('button')
    // 克隆按钮 + 冠军按钮（按 List.Item.actions 的顺序：[clone, champion]）
    const cloneBtn = buttons[0]
    fireEvent.click(cloneBtn)
    // 由于按钮内 stopPropagation，列表项 onClick 不应被触发
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('case 3: 点击「标记为冠军」按钮调用后端；is_champion=true 的行按钮 disabled', async () => {
    mockedChampion.mockResolvedValue({ data: makeVariant({ is_champion: true }) })

    const variants = [
      makeVariant({
        id: '11111111-aaaa-bbbb-cccc-000000000001',
        status: 'ready',
        is_champion: false,
      }),
      makeVariant({
        id: '22222222-aaaa-bbbb-cccc-000000000002',
        status: 'ready',
        is_champion: true,
      }),
    ]

    renderWithClient(
      <VariantList
        variants={variants}
        activeVariantId={null}
        onSelect={() => {}}
      />,
    )

    // 找出所有按钮：每行 2 个（克隆 + 冠军），共 4 个
    const buttons = screen.getAllByRole('button')
    expect(buttons.length).toBeGreaterThanOrEqual(4)

    // 第一行：未冠军，冠军按钮（index 1）应可点击
    const firstChampionBtn = buttons[1]
    expect(firstChampionBtn).not.toBeDisabled()
    fireEvent.click(firstChampionBtn)

    await waitFor(() => {
      expect(mockedChampion).toHaveBeenCalledTimes(1)
    })
    expect(mockedChampion).toHaveBeenCalledWith({
      variantId: '11111111-aaaa-bbbb-cccc-000000000001',
    })

    // 第二行：已冠军，冠军按钮（index 3）应 disabled
    const secondChampionBtn = buttons[3]
    expect(secondChampionBtn).toBeDisabled()
  })
})
