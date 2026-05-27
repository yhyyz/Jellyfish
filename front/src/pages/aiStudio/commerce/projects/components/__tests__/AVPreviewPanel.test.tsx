/**
 * AVPreviewPanel 组件单测（W20-T4，TDD RED 阶段先行）。
 *
 * 覆盖点：
 * 1. shot.dubbed_video_file_id 存在 → 渲染 <video>，src 解析为 resolveAssetUrl(file_id)。
 * 2. shot.dubbed_video_file_id 缺失 → 渲染 Empty + 触发按钮 + 任务中心入口。
 * 3. 点击触发按钮调用 CommerceTasksService.enqueueChapterAvExport，
 *    requestBody.chapter_id 与 prop 对齐。
 * 4. 触发请求挂起期间（mutation.isPending=true）按钮处于 disabled 状态，
 *    避免双触发。
 * 5. 抽屉中能看到「音色」与「字幕样式」两个 collapse panel 标题
 *    （加分项，验证嵌套 picker）。
 *
 * 实现要点：
 * - 通过 vi.spyOn 拦截 OpenAPI generated client 的入队方法（与 T2/T3 一致）。
 * - 通过 vi.mock 替换 sibling `workbench.queries` 中的 `useVoicePacks` /
 *   `useSubtitleStyles`，避免内嵌 picker 触发真实网络请求。
 * - antd Collapse / Drawer 在 jsdom 缺少 matchMedia / ResizeObserver，
 *   beforeAll 兜底补齐。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach, beforeAll } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import {
  CommerceTasksService,
  type ShotRead,
} from '../../../../../../services/generated'

// ---- antd 在 jsdom 缺失 API 兜底（与 SubtitleStylePicker.test 同款） ----
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

// ---- mock workbench.queries 中两个内嵌 picker 用到的 hook ----
// 这样 VoicePackPicker / SubtitleStylePicker 走假数据，不发真实请求。
vi.mock('../../workbench.queries', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  return {
    ...actual,
    useVoicePacks: () => ({ data: [], isLoading: false, isError: false }),
    useSubtitleStyles: () => ({ data: [], isLoading: false, isError: false }),
  }
})

import { AVPreviewPanel } from '../AVPreviewPanel'

/**
 * 构造 ShotRead fixture。默认无 dubbed_video_file_id（走 Empty 分支）。
 */
function makeShot(overrides: Partial<ShotRead> = {}): ShotRead {
  return {
    id: 'shot-1',
    chapter_id: 'chapter-1',
    index: 0,
    title: '镜头 1',
    extraction: {
      state: 'extracted_resolved',
      has_extracted: true,
    } as ShotRead['extraction'],
    ...overrides,
  }
}

/** 干净的 QueryClient，关闭 retry 避免 RED 用例等 retry 拖慢测试。 */
function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
}

/** 渲染 helper：包一层 QueryClientProvider。 */
function renderPanel(ui: React.ReactNode) {
  const client = makeClient()
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

// spyOn 的精确返回类型与 MockInstance<unknown> 之间存在 TS 兼容差，
// 测试只关心 mock API（mockResolvedValue / mockImplementationOnce 等），
// 这里用 any 作为别名故意放宽。
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let mockedEnqueueAvExport: any

beforeEach(() => {
  mockedEnqueueAvExport = vi.spyOn(
    CommerceTasksService,
    'enqueueChapterAvExportApiV1CommerceChapterAvExportPost',
  )
})

afterEach(() => {
  mockedEnqueueAvExport.mockRestore()
})

describe('AVPreviewPanel', () => {
  it('case 1: shot.dubbed_video_file_id 存在时渲染 <video>，src 含解析后的 file_id', () => {
    const shot = makeShot({ dubbed_video_file_id: 'av-final-001' })
    const { container } = renderPanel(
      <AVPreviewPanel chapterId="chapter-1" projectId="proj-1" shot={shot} />,
    )

    const video = container.querySelector('video')
    expect(video).not.toBeNull()
    // resolveAssetUrl 会把裸 file_id 转成 /api/v1/studio/files/{id}/download
    // 路径，断言只校验 src 字符串里能反推出来。
    expect(video?.getAttribute('src')).toContain('av-final-001')
  })

  it('case 2: shot.dubbed_video_file_id 缺失时渲染 Empty + 立即生成 + 任务中心入口', () => {
    const shot = makeShot({ dubbed_video_file_id: null })
    const { container } = renderPanel(
      <AVPreviewPanel chapterId="chapter-1" projectId="proj-1" shot={shot} />,
    )

    // 主区域不应有 <video>
    expect(container.querySelector('video')).toBeNull()
    // Empty 文案 + 两个按钮均可见
    expect(screen.getByText(/等待 chapter_av_export/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /立即生成/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /任务中心/ })).toBeInTheDocument()
  })

  it('case 3: 点击立即生成按钮调用 enqueueChapterAvExport，requestBody 含 chapter_id', async () => {
    const shot = makeShot({ dubbed_video_file_id: null })
    mockedEnqueueAvExport.mockResolvedValue({
      data: { task_id: 'task-av-1' },
    })

    renderPanel(
      <AVPreviewPanel chapterId="chapter-42" projectId="proj-1" shot={shot} />,
    )

    fireEvent.click(screen.getByRole('button', { name: /立即生成/ }))

    await waitFor(() => {
      expect(mockedEnqueueAvExport).toHaveBeenCalledTimes(1)
    })
    expect(mockedEnqueueAvExport).toHaveBeenCalledWith({
      requestBody: expect.objectContaining({ chapter_id: 'chapter-42' }),
    })
  })

  it('case 4: mutation 挂起期间立即生成按钮处于 disabled 状态，防止双触发', async () => {
    const shot = makeShot({ dubbed_video_file_id: null })
    // 给一个永不 resolve 的 promise，让 isPending 维持为 true。
    let resolveEnqueue: ((v: { data: { task_id: string } }) => void) | undefined
    mockedEnqueueAvExport.mockImplementationOnce(
      () =>
        new Promise<{ data: { task_id: string } }>((resolve) => {
          resolveEnqueue = resolve
        }),
    )

    renderPanel(
      <AVPreviewPanel chapterId="chapter-1" projectId="proj-1" shot={shot} />,
    )

    const btn = screen.getByRole('button', { name: /立即生成/ })
    expect(btn).not.toBeDisabled()

    fireEvent.click(btn)

    await waitFor(() => {
      const btnAfter = screen.getByRole('button', { name: /立即生成/ })
      expect(btnAfter).toBeDisabled()
    })

    // 收尾：释放挂起 promise，避免影响后续测试
    resolveEnqueue?.({ data: { task_id: 'task-av-1' } })
  })

  it('case 5: 抽屉嵌套面板能看到「音色」与「字幕样式」两个 collapse 标题（加分项）', () => {
    const shot = makeShot()
    renderPanel(
      <AVPreviewPanel chapterId="chapter-1" projectId="proj-1" shot={shot} />,
    )
    // 「音色」是 AVPreviewPanel 自己加的 panel 标题，唯一
    expect(screen.getByText('音色')).toBeInTheDocument()
    // 「字幕样式」在 SubtitleStylePicker Card 标题与 Collapse panel 标题都会出现，
    // 用 getAllByText 兜底，保证至少出现一次即满足。
    expect(screen.getAllByText('字幕样式').length).toBeGreaterThan(0)
  })
})
