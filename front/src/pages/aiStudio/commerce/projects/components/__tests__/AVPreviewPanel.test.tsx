/**
 * AVPreviewPanel 组件单测（W20-T4 / W31-T5）。
 *
 * 覆盖点：
 * 1. shot.dubbed_video_file_id 存在 → 渲染 <video>，src 解析为 resolveAssetUrl(file_id)。
 * 2. shot.dubbed_video_file_id 缺失 → 渲染 Empty + 触发按钮 + 任务中心入口。
 * 3. 点击触发按钮调用 CommerceTasksService.enqueueChapterAvExport，
 *    requestBody.chapter_id 与 prop 对齐 + 含 audio_mix_mode 字段。
 * 4. 触发请求挂起期间（mutation.isPending=true）按钮处于 disabled 状态，
 *    避免双触发。
 * 5. 抽屉中能看到「音色」「字幕样式」「音轨混合」三个 collapse panel。
 * 6. (W31) AudioMixMode toggle 默认 voice_only，切到 voice_bgm 时显示
 *    BGM 选择器；切到 full 时再显示 SFX 选择器 + ducking 滑块。
 * 7. (W31) 切换到 voice_bgm 后再触发生成，requestBody.audio_mix_mode 变为
 *    'voice_bgm'。
 *
 * 实现要点：
 * - 通过 vi.spyOn 拦截 OpenAPI generated client 的入队方法 +
 *   StudioFilesService 的列表方法。
 * - 通过 vi.mock 替换 sibling `workbench.queries` 中的 `useVoicePacks` /
 *   `useSubtitleStyles`，避免内嵌 picker 触发真实网络请求。
 * - 不挂载真实 i18n provider，断言时使用 t() 在缺失资源时回退的原始
 *   key（与 VoicePackPicker.test.tsx 同款做法）。
 * - antd Collapse / Drawer 在 jsdom 缺少 matchMedia / ResizeObserver，
 *   beforeAll 兜底补齐。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach, beforeAll } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import {
  CommerceTasksService,
  StudioChaptersService,
  StudioFilesService,
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
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let mockedListFiles: any
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let mockedPatchSegmentAudio: any

beforeEach(() => {
  mockedEnqueueAvExport = vi.spyOn(
    CommerceTasksService,
    'enqueueChapterAvExportApiV1CommerceChapterAvExportPost',
  )
  mockedListFiles = vi.spyOn(
    StudioFilesService,
    'listFilesApiApiV1StudioFilesGet',
  )
  mockedPatchSegmentAudio = vi.spyOn(
    StudioChaptersService,
    'patchChapterTimelineSegmentAudioApiV1StudioChaptersChapterIdTimelineSegmentsSegmentIdAudioPatch',
  )
  // 默认返回空列表，单个测试可以覆写。
  mockedListFiles.mockResolvedValue({
    data: { items: [], total: 0, page: 1, page_size: 50 },
  })
  // P5 W31-T8 默认 PATCH 成功，单个测试覆写为 reject 验证错误路径。
  mockedPatchSegmentAudio.mockResolvedValue({
    data: {
      id: 'seg-1',
      shot_id: 'shot-1',
      position: 0,
      bgm_file_id: null,
      sfx_file_id: null,
      bgm_ducking_db: -12,
      clip_status: 'ready',
      label: '镜头 1',
    },
  })
})

afterEach(() => {
  mockedEnqueueAvExport.mockRestore()
  mockedListFiles.mockRestore()
  mockedPatchSegmentAudio.mockRestore()
})

describe('AVPreviewPanel', () => {
  it('case 1: shot.dubbed_video_file_id 存在时渲染 <video>，src 含解析后的 file_id', () => {
    const shot = makeShot({ dubbed_video_file_id: 'av-final-001' })
    const { container } = renderPanel(
      <AVPreviewPanel chapterId="chapter-1" projectId="proj-1" shot={shot} />,
    )

    const video = container.querySelector('video')
    expect(video).not.toBeNull()
    expect(video?.getAttribute('src')).toContain('av-final-001')
  })

  it('case 2: shot.dubbed_video_file_id 缺失时渲染 Empty + 立即生成 + 任务中心入口', () => {
    const shot = makeShot({ dubbed_video_file_id: null })
    const { container } = renderPanel(
      <AVPreviewPanel chapterId="chapter-1" projectId="proj-1" shot={shot} />,
    )

    expect(container.querySelector('video')).toBeNull()
    // 不挂载真实 i18n provider 时 t() 回退到 key 本身：
    expect(screen.getByText('avPreview.emptyHint')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'avPreview.triggerExport' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'avPreview.viewTaskCenter' }),
    ).toBeInTheDocument()
  })

  it('case 3: 点击立即生成按钮调用 enqueueChapterAvExport，requestBody 含 chapter_id + audio_mix_mode', async () => {
    const shot = makeShot({ dubbed_video_file_id: null })
    mockedEnqueueAvExport.mockResolvedValue({
      data: { task_id: 'task-av-1' },
    })

    renderPanel(
      <AVPreviewPanel chapterId="chapter-42" projectId="proj-1" shot={shot} />,
    )

    fireEvent.click(
      screen.getByRole('button', { name: 'avPreview.triggerExport' }),
    )

    await waitFor(() => {
      expect(mockedEnqueueAvExport).toHaveBeenCalledTimes(1)
    })
    expect(mockedEnqueueAvExport).toHaveBeenCalledWith({
      requestBody: expect.objectContaining({
        chapter_id: 'chapter-42',
        audio_mix_mode: 'voice_only',
      }),
    })
  })

  it('case 4: mutation 挂起期间立即生成按钮处于 disabled 状态，防止双触发', async () => {
    const shot = makeShot({ dubbed_video_file_id: null })
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

    const btn = screen.getByRole('button', {
      name: 'avPreview.triggerExport',
    })
    expect(btn).not.toBeDisabled()

    fireEvent.click(btn)

    await waitFor(() => {
      const btnAfter = screen.getByRole('button', {
        name: 'avPreview.triggerExport',
      })
      expect(btnAfter).toBeDisabled()
    })

    // 收尾：释放挂起 promise，避免影响后续测试
    resolveEnqueue?.({ data: { task_id: 'task-av-1' } })
  })

  it('case 5: 抽屉嵌套面板能看到「音色」「字幕样式」「音轨混合」三个 collapse 标题', () => {
    const shot = makeShot()
    renderPanel(
      <AVPreviewPanel chapterId="chapter-1" projectId="proj-1" shot={shot} />,
    )
    expect(screen.getByText('avPreview.voicePanel')).toBeInTheDocument()
    expect(screen.getAllByText('avPreview.subtitlePanel').length).toBeGreaterThan(0)
    expect(screen.getByText('avPreview.audioMixModePanel')).toBeInTheDocument()
  })

  // -------- W31 新增 case --------

  it('case 6 (W31): voice_only 模式不显示 BGM/SFX/ducking 行', () => {
    const shot = makeShot()
    renderPanel(
      <AVPreviewPanel chapterId="chapter-1" projectId="proj-1" shot={shot} />,
    )
    // 默认 voice_only，BGM/SFX/ducking 行均不渲染
    expect(screen.queryByTestId('av-preview-bgm-row')).not.toBeInTheDocument()
    expect(screen.queryByTestId('av-preview-sfx-row')).not.toBeInTheDocument()
    expect(screen.queryByTestId('av-preview-ducking-row')).not.toBeInTheDocument()
  })

  it('case 7 (W31): 切到 voice_bgm 显示 BGM 行，但仍隐藏 SFX/ducking', () => {
    const shot = makeShot()
    renderPanel(
      <AVPreviewPanel chapterId="chapter-1" projectId="proj-1" shot={shot} />,
    )
    // 找到 voice_bgm Radio.Button 并点击切换
    const voiceBgmBtn = screen.getByRole('radio', {
      name: 'avPreview.audioMixMode.voice_bgm.label',
    })
    fireEvent.click(voiceBgmBtn)

    expect(screen.getByTestId('av-preview-bgm-row')).toBeInTheDocument()
    expect(screen.queryByTestId('av-preview-sfx-row')).not.toBeInTheDocument()
    expect(screen.queryByTestId('av-preview-ducking-row')).not.toBeInTheDocument()
  })

  it('case 8 (W31): 切到 full 显示 BGM + SFX + ducking 三行', () => {
    const shot = makeShot()
    renderPanel(
      <AVPreviewPanel chapterId="chapter-1" projectId="proj-1" shot={shot} />,
    )
    const fullBtn = screen.getByRole('radio', {
      name: 'avPreview.audioMixMode.full.label',
    })
    fireEvent.click(fullBtn)

    expect(screen.getByTestId('av-preview-bgm-row')).toBeInTheDocument()
    expect(screen.getByTestId('av-preview-sfx-row')).toBeInTheDocument()
    expect(screen.getByTestId('av-preview-ducking-row')).toBeInTheDocument()
  })

  it('case 9 (W31): 切到 voice_bgm 后触发生成，audio_mix_mode 透传到请求体', async () => {
    const shot = makeShot()
    mockedEnqueueAvExport.mockResolvedValue({ data: { task_id: 't-9' } })

    renderPanel(
      <AVPreviewPanel chapterId="chap-9" projectId="proj-9" shot={shot} />,
    )

    fireEvent.click(
      screen.getByRole('radio', {
        name: 'avPreview.audioMixMode.voice_bgm.label',
      }),
    )

    fireEvent.click(
      screen.getByRole('button', { name: 'avPreview.triggerExport' }),
    )

    await waitFor(() => {
      expect(mockedEnqueueAvExport).toHaveBeenCalledTimes(1)
    })
    expect(mockedEnqueueAvExport).toHaveBeenCalledWith({
      requestBody: expect.objectContaining({
        chapter_id: 'chap-9',
        audio_mix_mode: 'voice_bgm',
      }),
    })
  })

  it('case 10 (W31): voice_bgm 模式触发 list audio files 请求，filter type=audio', async () => {
    const shot = makeShot()
    mockedListFiles.mockResolvedValue({
      data: {
        items: [
          { id: 'f1', name: 'song1.mp3', type: 'audio' },
          { id: 'f2', name: 'image.png', type: 'image' },
        ],
        total: 2,
        page: 1,
        page_size: 50,
      },
    })

    renderPanel(
      <AVPreviewPanel chapterId="chap-10" projectId="proj-10" shot={shot} />,
    )

    fireEvent.click(
      screen.getByRole('radio', {
        name: 'avPreview.audioMixMode.voice_bgm.label',
      }),
    )

    await waitFor(() => {
      expect(mockedListFiles).toHaveBeenCalledTimes(1)
    })
    expect(mockedListFiles).toHaveBeenCalledWith(
      expect.objectContaining({ projectId: 'proj-10' }),
    )
  })

  // -------- W31-T8 PATCH segment audio mutation 接通 --------

  it('case 11 (W31-T8): voice_bgm 模式选 BGM → patchSegmentAudio 立即调用，参数含 bgm_file_id', async () => {
    const shot = makeShot()
    mockedListFiles.mockResolvedValue({
      data: {
        items: [{ id: 'bgm-99', name: 'song.mp3', type: 'audio' }],
        total: 1,
        page: 1,
        page_size: 50,
      },
    })
    renderPanel(
      <AVPreviewPanel
        chapterId="chap-11"
        projectId="proj-11"
        segmentId="seg-11"
        shot={shot}
      />,
    )
    fireEvent.click(
      screen.getByRole('radio', {
        name: 'avPreview.audioMixMode.voice_bgm.label',
      }),
    )

    await waitFor(() => {
      expect(mockedListFiles).toHaveBeenCalled()
    })

    // antd Select 在 jsdom 下 aria-label 同时落到外层 Form-style div 与 inner
    // combobox 上，screen.getByLabelText 会拿到多个匹配项；scoped 到 testid
    // div 后用 role=combobox 精确锁定真正的 Select trigger。
    const bgmRow = screen.getByTestId('av-preview-bgm-row')
    const bgmCombobox = within(bgmRow).getByRole('combobox')
    fireEvent.mouseDown(bgmCombobox)
    await waitFor(() => {
      expect(screen.getByText('song.mp3')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('song.mp3'))

    await waitFor(() => {
      expect(mockedPatchSegmentAudio).toHaveBeenCalledTimes(1)
    })
    expect(mockedPatchSegmentAudio).toHaveBeenCalledWith({
      chapterId: 'chap-11',
      segmentId: 'seg-11',
      requestBody: expect.objectContaining({ bgm_file_id: 'bgm-99' }),
    })
  })

  it('case 12 (W31-T8): full 模式拖 ducking 滑块 + 松开 → onAfterChange 触发 mutate', async () => {
    const shot = makeShot()
    renderPanel(
      <AVPreviewPanel
        chapterId="chap-12"
        projectId="proj-12"
        segmentId="seg-12"
        shot={shot}
      />,
    )

    fireEvent.click(
      screen.getByRole('radio', {
        name: 'avPreview.audioMixMode.full.label',
      }),
    )

    // antd Slider (rc-slider 10.3.1) 内部 onKeyDown 用 ``e.which || e.keyCode``
    // 判断方向键，并在同一回调里同步触发 onChange + onAfterChange。
    // 必须传 keyCode=37 (LEFT)，``key: 'ArrowLeft'`` 不会被识别。
    const duckingRow = screen.getByTestId('av-preview-ducking-row')
    const slider = within(duckingRow).getByRole('slider')
    fireEvent.keyDown(slider, { key: 'ArrowLeft', keyCode: 37, which: 37 })

    await waitFor(() => {
      expect(mockedPatchSegmentAudio).toHaveBeenCalled()
    })
    const lastCall = mockedPatchSegmentAudio.mock.calls.at(-1)?.[0]
    expect(lastCall.chapterId).toBe('chap-12')
    expect(lastCall.segmentId).toBe('seg-12')
    expect(lastCall.requestBody).toHaveProperty('bgm_ducking_db')
    expect(typeof lastCall.requestBody.bgm_ducking_db).toBe('number')
  })

  it('case 13 (W31-T8): segmentId 缺失时改 BGM 不发请求（避免 404 噪声）', async () => {
    const shot = makeShot()
    mockedListFiles.mockResolvedValue({
      data: {
        items: [{ id: 'bgm-x', name: 'x.mp3', type: 'audio' }],
        total: 1,
        page: 1,
        page_size: 50,
      },
    })
    renderPanel(
      <AVPreviewPanel chapterId="chap-13" projectId="proj-13" shot={shot} />,
    )
    fireEvent.click(
      screen.getByRole('radio', {
        name: 'avPreview.audioMixMode.voice_bgm.label',
      }),
    )
    await waitFor(() => {
      expect(mockedListFiles).toHaveBeenCalled()
    })

    const bgmRow = screen.getByTestId('av-preview-bgm-row')
    const bgmCombobox = within(bgmRow).getByRole('combobox')
    fireEvent.mouseDown(bgmCombobox)
    await waitFor(() => {
      expect(screen.getByText('x.mp3')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('x.mp3'))

    // 给 react-query 一个 microtask 机会，确认确实没 fire mutate（segmentId 为空兜底）
    await new Promise((r) => setTimeout(r, 50))
    expect(mockedPatchSegmentAudio).not.toHaveBeenCalled()
  })

  it('case 14 (W31-T8): mutate reject → message.error，UI 状态不回滚', async () => {
    const shot = makeShot()
    mockedListFiles.mockResolvedValue({
      data: {
        items: [{ id: 'bgm-fail', name: 'fail.mp3', type: 'audio' }],
        total: 1,
        page: 1,
        page_size: 50,
      },
    })
    mockedPatchSegmentAudio.mockRejectedValue(new Error('boom'))

    renderPanel(
      <AVPreviewPanel
        chapterId="chap-14"
        projectId="proj-14"
        segmentId="seg-14"
        shot={shot}
      />,
    )
    fireEvent.click(
      screen.getByRole('radio', {
        name: 'avPreview.audioMixMode.voice_bgm.label',
      }),
    )
    await waitFor(() => {
      expect(mockedListFiles).toHaveBeenCalled()
    })

    const bgmRow = screen.getByTestId('av-preview-bgm-row')
    const bgmCombobox = within(bgmRow).getByRole('combobox')
    fireEvent.mouseDown(bgmCombobox)
    await waitFor(() => {
      expect(screen.getByText('fail.mp3')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('fail.mp3'))

    await waitFor(() => {
      expect(mockedPatchSegmentAudio).toHaveBeenCalled()
    })
    // UI 上选中值不被回滚 —— Select 的 value 由本地 state 持有，不受
    // mutation 失败影响。这是设计契约：让用户能纠正后重试。
    expect(screen.getAllByText('fail.mp3').length).toBeGreaterThan(0)
  })

  it('case 15 (W31-T8): audio_mix_mode toggle 不触发 patchSegmentAudio (mode 是 export 入参)', async () => {
    const shot = makeShot()
    renderPanel(
      <AVPreviewPanel
        chapterId="chap-15"
        projectId="proj-15"
        segmentId="seg-15"
        shot={shot}
      />,
    )
    fireEvent.click(
      screen.getByRole('radio', {
        name: 'avPreview.audioMixMode.voice_bgm.label',
      }),
    )
    fireEvent.click(
      screen.getByRole('radio', {
        name: 'avPreview.audioMixMode.full.label',
      }),
    )
    fireEvent.click(
      screen.getByRole('radio', { name: 'avPreview.audioMixMode.off.label' }),
    )

    // 给一个 microtask 机会，确认确实没发起 PATCH
    await new Promise((r) => setTimeout(r, 50))
    expect(mockedPatchSegmentAudio).not.toHaveBeenCalled()
  })

  it('case 16 (W31-T8): full 模式选 SFX → patchSegmentAudio 调用，参数含 sfx_file_id', async () => {
    const shot = makeShot()
    mockedListFiles.mockResolvedValue({
      data: {
        items: [{ id: 'sfx-zap', name: 'zap.mp3', type: 'audio' }],
        total: 1,
        page: 1,
        page_size: 50,
      },
    })
    renderPanel(
      <AVPreviewPanel
        chapterId="chap-16"
        projectId="proj-16"
        segmentId="seg-16"
        shot={shot}
      />,
    )
    fireEvent.click(
      screen.getByRole('radio', {
        name: 'avPreview.audioMixMode.full.label',
      }),
    )
    await waitFor(() => {
      expect(mockedListFiles).toHaveBeenCalled()
    })

    const sfxRow = screen.getByTestId('av-preview-sfx-row')
    const sfxCombobox = within(sfxRow).getByRole('combobox')
    fireEvent.mouseDown(sfxCombobox)
    await waitFor(() => {
      // SFX dropdown 与 BGM dropdown 共享 audioOptions —— getAllByText 兜底
      expect(screen.getAllByText('zap.mp3').length).toBeGreaterThan(0)
    })
    fireEvent.click(screen.getAllByText('zap.mp3')[0])

    await waitFor(() => {
      expect(mockedPatchSegmentAudio).toHaveBeenCalledTimes(1)
    })
    expect(mockedPatchSegmentAudio).toHaveBeenCalledWith({
      chapterId: 'chap-16',
      segmentId: 'seg-16',
      requestBody: expect.objectContaining({ sfx_file_id: 'sfx-zap' }),
    })
  })

  it('case 17 (W31-followup #6): full 模式拖 sfx_offset 滑块 + 松开 → onAfterChange 触发 mutate', async () => {
    const shot = makeShot()
    renderPanel(
      <AVPreviewPanel
        chapterId="chap-17"
        projectId="proj-17"
        segmentId="seg-17"
        shot={shot}
      />,
    )

    fireEvent.click(
      screen.getByRole('radio', {
        name: 'avPreview.audioMixMode.full.label',
      }),
    )

    // antd Slider 用 keyCode 触发 onChange + onAfterChange 同步回调，
    // 与 case 12 ducking 滑块同一套交互机制；用 ArrowRight 让初始 0 上移。
    const sfxOffsetRow = screen.getByTestId('av-preview-sfx-offset-row')
    const slider = within(sfxOffsetRow).getByRole('slider')
    fireEvent.keyDown(slider, { key: 'ArrowRight', keyCode: 39, which: 39 })

    await waitFor(() => {
      expect(mockedPatchSegmentAudio).toHaveBeenCalled()
    })
    const lastCall = mockedPatchSegmentAudio.mock.calls.at(-1)?.[0]
    expect(lastCall.chapterId).toBe('chap-17')
    expect(lastCall.segmentId).toBe('seg-17')
    expect(lastCall.requestBody).toHaveProperty('sfx_offset_ms')
    expect(typeof lastCall.requestBody.sfx_offset_ms).toBe('number')
    expect(lastCall.requestBody.sfx_offset_ms).toBeGreaterThan(0)
  })
})
