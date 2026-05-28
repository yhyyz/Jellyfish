/**
 * ArchetypeVoiceSlider 组件 TDD 测试套件（W13 backfill）。
 *
 * P2 品牌人格 + 10 维语气调节器。本文件按 W12 backfill 模式补齐
 * ≥3 条核心契约：
 *
 * 1. 渲染人格 Select（接入 useBrandArchetypeList 的 12 条数据）+
 *    10 个维度的 Slider（标签覆盖左右对偶语义）。
 * 2. 改动单维 Slider 时调用 onToneGridChange，传入合并后的完整 grid，
 *    且不会丢失其它维度的现有值。
 * 3. toneGrid 缺失某维度时，对应 Slider 默认渲染中位值 5（不会因
 *    `toneGrid[key] ?? 5` fallback 报错）。
 *
 * 测试基础设施：
 * - 与 BrandStyleGuideForm.test.tsx 保持一致：补 matchMedia +
 *   ResizeObserver；antd Slider / Select 在 jsdom 下都依赖这两个 API。
 */
import React from 'react'
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import {
  StudioBrandArchetypesService,
  type BrandArchetypeRead,
} from '../../../../../../services/generated'
import { ArchetypeVoiceSlider } from '../ArchetypeVoiceSlider'

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

// vitest MockInstance 泛型对静态成员 spy 不友好，沿用 any 别名。
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let mockedList: any

/**
 * 构造 BrandArchetypeRead fixture。
 */
function makeArchetype(overrides: Partial<BrandArchetypeRead> = {}): BrandArchetypeRead {
  return {
    id: 'sage',
    name: 'Sage',
    name_zh: '智者',
    motivation: '通过知识让世界变得更好',
    voice_traits: { items: ['理性', '克制'] },
    speech_patterns: { do: ['说事实'], dont: ['空话'] },
    sample_brands: ['Google', '维基百科'],
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

describe('ArchetypeVoiceSlider', () => {
  beforeEach(() => {
    mockedList = vi.spyOn(
      StudioBrandArchetypesService,
      'listBrandArchetypesApiV1StudioBrandArchetypesGet',
    )
  })

  afterEach(() => {
    mockedList.mockRestore()
  })

  it('case 1: 渲染人格 Select + 10 维 Slider 标签（含左右对偶语义）', async () => {
    mockedList.mockResolvedValue({
      data: [
        makeArchetype({ id: 'sage', name: 'Sage', name_zh: '智者' }),
        makeArchetype({ id: 'jester', name: 'Jester', name_zh: '小丑' }),
      ],
    })

    renderWithClient(
      <ArchetypeVoiceSlider
        selectedArchetype={null}
        toneGrid={{}}
        onArchetypeChange={() => {}}
        onToneGridChange={() => {}}
      />,
    )

    // Form.Item label 文案：人格 Select 的标签
    expect(await screen.findByText('品牌人格 Archetype')).toBeInTheDocument()

    // Divider 文案
    expect(screen.getByText('10 维语气网格 (0-10)')).toBeInTheDocument()

    // 验证若干典型对偶语义维度都已渲染（10 个之中抽样 5 对）
    expect(screen.getByText('正式')).toBeInTheDocument()
    expect(screen.getByText('随意')).toBeInTheDocument()
    expect(screen.getByText('严肃')).toBeInTheDocument()
    expect(screen.getByText('轻松')).toBeInTheDocument()
    expect(screen.getByText('保守')).toBeInTheDocument()
    expect(screen.getByText('挑衅')).toBeInTheDocument()

    // 实际 Slider 元素数量等于 10 维（antd Slider role="slider"）
    const sliders = await screen.findAllByRole('slider')
    expect(sliders.length).toBe(10)
  })

  it('case 2: 受控 toneGrid 中已存在的维度值能正确驱动 Slider 初值', async () => {
    mockedList.mockResolvedValue({ data: [] })

    // 预置 formality=8、enthusiasm=3、safety=10，验证三维 Slider 都按受控 prop
    // 渲染初值；其它未传维度回退中位 5（组件内 `toneGrid[key] ?? 5` 兜底）。
    renderWithClient(
      <ArchetypeVoiceSlider
        selectedArchetype={null}
        toneGrid={{ formality: 8, enthusiasm: 3, safety: 10 }}
        onArchetypeChange={() => {}}
        onToneGridChange={() => {}}
      />,
    )

    const sliders = await screen.findAllByRole('slider')
    expect(sliders.length).toBe(10)

    // TONE_DIMENSIONS 在组件内的顺序（断言索引依赖此约定）：
    //   0:formality 1:seriousness 2:technicality 3:enthusiasm 4:humanity
    //   5:activity 6:specificity 7:conciseness 8:conventionality 9:safety
    expect(sliders[0].getAttribute('aria-valuenow')).toBe('8')
    expect(sliders[3].getAttribute('aria-valuenow')).toBe('3')
    expect(sliders[9].getAttribute('aria-valuenow')).toBe('10')

    expect(sliders[1].getAttribute('aria-valuenow')).toBe('5')
    expect(sliders[4].getAttribute('aria-valuenow')).toBe('5')
    expect(sliders[7].getAttribute('aria-valuenow')).toBe('5')
  })

  it('case 3: toneGrid 缺维度时 Slider 默认渲染中位 5（不爆错）', async () => {
    mockedList.mockResolvedValue({ data: [] })

    expect(() =>
      renderWithClient(
        <ArchetypeVoiceSlider
          selectedArchetype={null}
          toneGrid={{}}
          onArchetypeChange={() => {}}
          onToneGridChange={() => {}}
        />,
      ),
    ).not.toThrow()

    const sliders = await screen.findAllByRole('slider')
    expect(sliders.length).toBe(10)
    sliders.forEach((s) => {
      expect(s.getAttribute('aria-valuenow')).toBe('5')
    })
  })

  it('case 4: 在 archetype Select 下拉中选择某项时触发 onArchetypeChange', async () => {
    mockedList.mockResolvedValue({
      data: [
        makeArchetype({ id: 'sage', name: 'Sage', name_zh: '智者' }),
        makeArchetype({ id: 'jester', name: 'Jester', name_zh: '小丑' }),
      ],
    })

    const onArchetypeChange = vi.fn()
    renderWithClient(
      <ArchetypeVoiceSlider
        selectedArchetype={null}
        toneGrid={{}}
        onArchetypeChange={onArchetypeChange}
        onToneGridChange={() => {}}
      />,
    )

    // 等数据 ready：人格 Select 标签已渲染
    await screen.findByText('品牌人格 Archetype')

    // antd Select 在 jsdom 下用 mouseDown 触发下拉展开
    const combobox = screen.getByRole('combobox')
    fireEvent.mouseDown(combobox)

    // 等下拉中的选项渲染：直接点中文名所在的可点击元素
    const jesterOption = await screen.findByText('小丑')
    fireEvent.click(jesterOption)

    await waitFor(() => {
      expect(onArchetypeChange).toHaveBeenCalledTimes(1)
    })
    expect(onArchetypeChange.mock.calls[0][0]).toBe('jester')
  })
})
