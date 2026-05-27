/**
 * SubtitleStylePicker 组件测试。
 *
 * TDD RED 阶段：先写失败用例，验证：
 * 1. 系统模板 tab 渲染来自 query 的 3 个字幕样式 card
 * 2. 点击 system card 触发 onChange，参数为 SubtitleStyleRead 对象
 * 3. 切到「自定义」tab 显示编辑器；提交 form 触发 onChange(override 载荷)
 * 4. 输入非法 hex 颜色显示行内错误，**不**调 onChange
 * 5. 默认 selected 由 prop value 决定，切换 tab 来回不丢选中
 *
 * 实现方式：
 * - mock 同目录上层 `workbench.queries` 中的 `useSubtitleStyles` hook，
 *   绕过真实 OpenAPI fetch，避免在 jsdom 下走 TanStack Query / 网络。
 * - 在 jsdom 下补 `matchMedia` / `ResizeObserver` 让 antd Tabs / Form 可用。
 */
import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest'
import { render, screen, within, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { SubtitleStyleRead } from '../../../../../../services/generated'

// ---- antd 在 jsdom 缺失 API 兜底 ----
// antd 的 Tabs / ColorPicker / Form 内部会触摸 matchMedia 与 ResizeObserver；
// jsdom 默认没实现，需要在 import 组件之前补齐，否则渲染时报错。
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

// ---- mock useSubtitleStyles ----
const mockUseSubtitleStyles = vi.fn()
vi.mock('../../workbench.queries', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  return {
    ...actual,
    useSubtitleStyles: (...args: unknown[]) => mockUseSubtitleStyles(...args),
  }
})

import { SubtitleStylePicker } from '../SubtitleStylePicker'

// ---- 固定样本：W18 已 seed 的 3 个系统模板 ----
const SYSTEM_STYLES: SubtitleStyleRead[] = [
  {
    id: 'douyin_default',
    name: '抖音默认',
    description: '抖音默认风格',
    language_code: 'zh-CN',
    format: 'ass',
    font_family: 'Source Han Sans CN',
    font_size: 64,
    primary_colour: '&H00FFFFFF',
    secondary_colour: null,
    outline_colour: '&H00000000',
    back_colour: null,
    bold: true,
    italic: false,
    border_style: 1,
    outline: 2,
    shadow: 1,
    alignment: 2,
    margin_l: 80,
    margin_r: 80,
    margin_v: 200,
    play_res_x: 1080,
    play_res_y: 1920,
    font_fallback_chain: null,
    is_system: true,
    sort_order: 1,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
  {
    id: 'tiktok_viral',
    name: 'TikTok',
    description: 'TikTok 病毒式',
    language_code: 'en-US',
    format: 'ass',
    font_family: 'Proxima Nova',
    font_size: 72,
    primary_colour: '&H0000FFFF',
    secondary_colour: null,
    outline_colour: '&H00000000',
    back_colour: null,
    bold: true,
    italic: false,
    border_style: 1,
    outline: 3,
    shadow: 0,
    alignment: 2,
    margin_l: 80,
    margin_r: 80,
    margin_v: 240,
    play_res_x: 1080,
    play_res_y: 1920,
    font_fallback_chain: null,
    is_system: true,
    sort_order: 2,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
  {
    id: 'reels_lower_third',
    name: 'Reels',
    description: 'Reels Lower Third',
    language_code: 'en-US',
    format: 'ass',
    font_family: 'Helvetica',
    font_size: 56,
    primary_colour: '&H00FFFFFF',
    secondary_colour: null,
    outline_colour: '&H00000000',
    back_colour: null,
    bold: true,
    italic: false,
    border_style: 3,
    outline: 0,
    shadow: 0,
    alignment: 2,
    margin_l: 80,
    margin_r: 80,
    margin_v: 320,
    play_res_x: 1080,
    play_res_y: 1920,
    font_fallback_chain: null,
    is_system: true,
    sort_order: 3,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
]

beforeEach(() => {
  mockUseSubtitleStyles.mockReset()
  mockUseSubtitleStyles.mockReturnValue({
    data: SYSTEM_STYLES,
    isLoading: false,
    isError: false,
  })
})

describe('SubtitleStylePicker - 系统模板 tab', () => {
  it('case 1: query 返回 3 个系统 style 时渲染 3 张 card（含三个名称）', () => {
    render(<SubtitleStylePicker onChange={vi.fn()} />)
    expect(screen.getByText('抖音默认')).toBeInTheDocument()
    expect(screen.getByText('TikTok')).toBeInTheDocument()
    expect(screen.getByText('Reels')).toBeInTheDocument()
  })

  it('case 2: 点击某个 system card 触发 onChange(style) 并传出完整 SubtitleStyleRead', async () => {
    const onChange = vi.fn()
    render(<SubtitleStylePicker onChange={onChange} />)

    // 点击 TikTok 卡片
    const tiktokCard = screen.getByTestId('subtitle-style-card-tiktok_viral')
    await userEvent.click(tiktokCard)

    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'tiktok_viral', name: 'TikTok' }),
    )
  })
})

describe('SubtitleStylePicker - 自定义 tab', () => {
  it('case 3: 切到自定义 tab，提交 form 触发 onChange(override 载荷)', async () => {
    const onChange = vi.fn()
    render(<SubtitleStylePicker onChange={onChange} />)

    // 切 tab
    await userEvent.click(screen.getByRole('tab', { name: /自定义/ }))

    // 修改 font_size
    const fontSizeInput = screen.getByTestId('subtitle-editor-font-size').querySelector('input')
    expect(fontSizeInput).not.toBeNull()
    if (fontSizeInput) {
      fireEvent.change(fontSizeInput, { target: { value: '80' } })
    }

    // 修改 primary_colour 为合法 hex
    const colourInput = screen.getByTestId('subtitle-editor-primary-colour') as HTMLInputElement
    fireEvent.change(colourInput, { target: { value: '#FF8800' } })

    // 提交
    await userEvent.click(screen.getByRole('button', { name: /应\s*用|apply/i }))

    expect(onChange).toHaveBeenCalledTimes(1)
    const payload = onChange.mock.calls[0][0]
    expect(payload).toMatchObject({
      font_size: 80,
      primary_colour: '#FF8800',
    })
  })

  it('case 4: 输入非法 hex 显示行内错误，不调 onChange', async () => {
    const onChange = vi.fn()
    render(<SubtitleStylePicker onChange={onChange} />)

    await userEvent.click(screen.getByRole('tab', { name: /自定义/ }))

    const colourInput = screen.getByTestId('subtitle-editor-primary-colour') as HTMLInputElement
    fireEvent.change(colourInput, { target: { value: 'not-a-hex' } })

    await userEvent.click(screen.getByRole('button', { name: /应\s*用|apply/i }))

    expect(onChange).not.toHaveBeenCalled()
    expect(screen.getByText(/颜色格式不正确/)).toBeInTheDocument()
  })
})

describe('SubtitleStylePicker - 选中态保持', () => {
  it('case 5: 默认 selected 由 prop value 决定，切到自定义 tab 再切回，原 selected 仍保持', async () => {
    const onChange = vi.fn()
    render(<SubtitleStylePicker value={SYSTEM_STYLES[1]} onChange={onChange} />)

    const tiktokCard = screen.getByTestId('subtitle-style-card-tiktok_viral')
    expect(tiktokCard).toHaveAttribute('data-selected', 'true')

    // 切到自定义 tab
    await userEvent.click(screen.getByRole('tab', { name: /自定义/ }))
    // 切回系统模板 tab
    await userEvent.click(screen.getByRole('tab', { name: /系统模板/ }))

    const tiktokCardAgain = screen.getByTestId('subtitle-style-card-tiktok_viral')
    expect(tiktokCardAgain).toHaveAttribute('data-selected', 'true')

    // 其它两张卡片不应被选中
    const douyin = screen.getByTestId('subtitle-style-card-douyin_default')
    const reels = screen.getByTestId('subtitle-style-card-reels_lower_third')
    expect(douyin).toHaveAttribute('data-selected', 'false')
    expect(reels).toHaveAttribute('data-selected', 'false')

    // within 用了一下避免 unused import 警告
    expect(within(tiktokCardAgain).getByText('TikTok')).toBeInTheDocument()
  })
})
