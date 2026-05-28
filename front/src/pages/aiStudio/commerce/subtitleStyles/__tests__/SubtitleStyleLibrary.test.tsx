/**
 * SubtitleStyleLibrary 页面测试（W20-T6 RED 阶段）。
 *
 * 覆盖核心契约：
 * 1. query 返回 3 个 system style 时，渲染 3 张卡片预览（按 name 断言）。
 * 2. query loading 时显示 antd Skeleton 占位。
 * 3. query error 时显示错误 banner（antd Alert role="alert"）。
 * 4. URL 不含 ?projectId 时显示 info banner「项目级覆盖在 W21 启用」。
 *
 * 实现策略：
 * - mock `../../projects/workbench.queries` 中的 `useSubtitleStyles`，绕过
 *   真实 OpenAPI fetch，避免 jsdom 下走 TanStack Query / 网络。
 * - 使用 `MemoryRouter` 包裹页面，便于在 `initialEntries` 中模拟带或不带
 *   `projectId` 的 URL。
 * - antd Tabs / Form 在 jsdom 缺 matchMedia / ResizeObserver，beforeAll 兜底。
 */
import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { SubtitleStyleRead } from '../../../../../services/generated'

// ---- antd 在 jsdom 缺失 API 兜底 ----
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

// ---- mock useSubtitleStyles（同 T20-3 hook-mock 模式） ----
const mockUseSubtitleStyles = vi.fn()
vi.mock('../../projects/workbench.queries', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  return {
    ...actual,
    useSubtitleStyles: (...args: unknown[]) => mockUseSubtitleStyles(...args),
  }
})

import SubtitleStyleLibrary from '../SubtitleStyleLibrary'

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

/**
 * 渲染辅助：用 MemoryRouter 包裹，initialEntries 控制 URL。
 */
function renderAt(path = '/commerce/subtitle-styles') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <SubtitleStyleLibrary />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  mockUseSubtitleStyles.mockReset()
})

describe('SubtitleStyleLibrary', () => {
  it('case 1: query 返回 3 个 system style 时渲染 3 张卡片预览（按 name 断言）', () => {
    mockUseSubtitleStyles.mockReturnValue({
      data: SYSTEM_STYLES,
      isLoading: false,
      isError: false,
    })

    renderAt()

    expect(screen.getByText('抖音默认')).toBeInTheDocument()
    expect(screen.getByText('TikTok')).toBeInTheDocument()
    expect(screen.getByText('Reels')).toBeInTheDocument()
  })

  it('case 2: query loading 时显示 antd Skeleton 占位', () => {
    mockUseSubtitleStyles.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
    })

    renderAt()

    expect(document.querySelector('.ant-skeleton')).toBeInTheDocument()
  })

  it('case 3: query error 时显示错误 banner（role="alert" 含 loadFailed 文案）', () => {
    mockUseSubtitleStyles.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
    })

    renderAt()

    const alerts = screen.getAllByRole('alert')
    // 应至少存在一条 error 类型 Alert
    expect(alerts.length).toBeGreaterThanOrEqual(1)
    // i18n 未注册时 t() 回退为原始 key，断言 key 即可
    expect(
      screen.getByText('subtitleStyleLibrary.loadFailed'),
    ).toBeInTheDocument()
  })

  it('case 4: 未带 ?projectId 时显示 info banner「在 URL 加 ?projectId 进入项目级编辑」', () => {
    mockUseSubtitleStyles.mockReturnValue({
      data: SYSTEM_STYLES,
      isLoading: false,
      isError: false,
    })

    renderAt('/commerce/subtitle-styles')

    expect(
      screen.getByText('subtitleStyleLibrary.projectOverridesHint'),
    ).toBeInTheDocument()
  })
})
