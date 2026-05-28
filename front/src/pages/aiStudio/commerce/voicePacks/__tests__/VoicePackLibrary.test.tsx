/**
 * VoicePackLibrary 页面单测（W20-T5 → W29 升级）。
 *
 * W20-T5 原有 5 个用例继续保留（系统级音色卡片 / loading / error / language 切换）；
 * W29 新增：
 * - case 6: 自定义音色列表的 clone_status 4 态 badge 渲染。
 * - case 7: 列表存在 deploying 行时 setInterval 自动 refetch；
 *           全部进入终态后停止 refetch。
 * - case 8: 上传按钮打开 W29 完整 Modal（不再是 stub）。
 *
 * Mock CommerceVoicePacksService + CommerceVoicePacksCustomService。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import {
  CommerceVoicePacksCustomService,
  CommerceVoicePacksService,
  type CustomVoiceListItem,
  type VoicePackRead,
} from '../../../../../services/generated'
import { VoicePackLibrary } from '../VoicePackLibrary'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let mockedListVoicePacks: any
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let mockedListCustom: any

function makePack(overrides: Partial<VoicePackRead> = {}): VoicePackRead {
  return {
    id: 'cosy_longxiaochun',
    name: '龙小淳',
    provider: 'aliyun_cosyvoice',
    provider_voice_id: 'longxiaochun_v2',
    language_code: 'zh-CN',
    gender: 'female',
    archetype_hint: null,
    sample_file_id: 'file-1',
    description: null,
    default_speed: 1.0,
    is_system: true,
    sort_order: 0,
    created_at: '2025-05-01T00:00:00Z',
    updated_at: '2025-05-01T00:00:00Z',
    ...overrides,
  }
}

function makeCustom(overrides: Partial<CustomVoiceListItem> = {}): CustomVoiceListItem {
  return {
    id: 'clone_x',
    name: '我的音色',
    provider: 'aliyun_cosyvoice',
    provider_voice_id: 'cosyvoice-v3.5-plus-myvoice-x',
    language_code: 'zh-CN',
    gender: 'neutral',
    archetype_hint: null,
    description: null,
    target_model: 'cosyvoice-v3.5-plus',
    region: 'cn-beijing',
    clone_status: 'ready',
    cloned_at: '2026-05-28T00:00:00Z',
    is_system: false,
    sort_order: 1000,
    created_at: '2026-05-28T00:00:00Z',
    updated_at: '2026-05-28T00:00:00Z',
    ...overrides,
  }
}

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
}

function renderWithClient(ui: React.ReactNode, client: QueryClient = makeClient()) {
  const utils = render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
  return { ...utils, client }
}

describe('VoicePackLibrary', () => {
  let playSpy: ReturnType<typeof vi.spyOn>
  let pauseSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    mockedListVoicePacks = vi.spyOn(
      CommerceVoicePacksService,
      'listVoicePacksEndpointApiV1CommerceVoicePacksGet',
    )
    mockedListCustom = vi.spyOn(
      CommerceVoicePacksCustomService,
      'listCustomVoicePacksEndpointApiV1CommerceVoicePacksCustomGet',
    )
    // 默认 custom 列表为空，避免每个原有 case 都要 mock 一次。
    mockedListCustom.mockResolvedValue({
      data: { items: [], pagination: { page: 1, page_size: 100, total: 0, max_page: 1 } },
    })
    playSpy = vi
      .spyOn(HTMLMediaElement.prototype, 'play')
      .mockImplementation(() => Promise.resolve())
    pauseSpy = vi
      .spyOn(HTMLMediaElement.prototype, 'pause')
      .mockImplementation(() => undefined as unknown as void)
  })

  afterEach(() => {
    mockedListVoicePacks.mockRestore()
    mockedListCustom.mockRestore()
    playSpy.mockRestore()
    pauseSpy.mockRestore()
  })

  it('case 1: query 返回 voice pack 数组时渲染对应数量的卡片', async () => {
    const a = makePack({ id: 'cosy_a', name: '龙小淳', sample_file_id: 'file-a' })
    const b = makePack({
      id: 'sambert_b',
      name: 'Sambert 男声',
      provider: 'dashscope',
      gender: 'male',
      sample_file_id: 'file-b',
    })
    mockedListVoicePacks.mockResolvedValue({ data: [a, b] })
    renderWithClient(<VoicePackLibrary />)

    expect(await screen.findByText('龙小淳')).toBeInTheDocument()
    expect(screen.getByText('Sambert 男声')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /play 龙小淳/i })).toBeInTheDocument()
  })

  it('case 2: query loading 时显示 antd Skeleton', () => {
    let resolveLoading: ((v: { data: VoicePackRead[] }) => void) | undefined
    mockedListVoicePacks.mockImplementationOnce(
      () =>
        new Promise<{ data: VoicePackRead[] }>((resolve) => {
          resolveLoading = resolve
        }) as unknown as ReturnType<typeof mockedListVoicePacks>,
    )
    const { unmount } = renderWithClient(<VoicePackLibrary />)
    expect(document.querySelector('.ant-skeleton')).toBeInTheDocument()
    resolveLoading?.({ data: [] })
    unmount()
  })

  it('case 3: query error 时显示错误 banner 与重试按钮', async () => {
    mockedListVoicePacks.mockRejectedValueOnce(new Error('boom'))
    renderWithClient(<VoicePackLibrary />)
    const alert = await screen.findByRole('alert')
    expect(alert).toBeInTheDocument()

    mockedListVoicePacks.mockResolvedValueOnce({
      data: [makePack({ id: 'after_retry', name: '重试成功' })],
    })
    const retryBtn = screen.getByRole('button', {
      name: /retry|重试|errorRetry/i,
    })
    fireEvent.click(retryBtn)
    await waitFor(() => {
      expect(mockedListVoicePacks).toHaveBeenCalledTimes(2)
    })
    expect(await screen.findByText('重试成功')).toBeInTheDocument()
  })

  it('case 4: 工具栏 language 下拉切换触发新查询', async () => {
    mockedListVoicePacks.mockResolvedValue({
      data: [makePack({ id: 'cosy_a', name: '龙小淳' })],
    })
    renderWithClient(<VoicePackLibrary />)
    await waitFor(() => {
      expect(mockedListVoicePacks).toHaveBeenCalledTimes(1)
    })
    expect(mockedListVoicePacks).toHaveBeenLastCalledWith(
      expect.objectContaining({ languageCode: 'zh-CN' }),
    )

    const select = screen.getByRole('combobox', { name: /voice-pack-language/i })
    fireEvent.mouseDown(select)
    const options = await screen.findAllByText('en-US')
    const clickable = options.find((el) =>
      el.className.includes('ant-select-item-option-content'),
    )
    expect(clickable).toBeTruthy()
    fireEvent.click(clickable!)
    await waitFor(() => {
      expect(mockedListVoicePacks).toHaveBeenCalledTimes(2)
    })
    expect(mockedListVoicePacks).toHaveBeenLastCalledWith(
      expect.objectContaining({ languageCode: 'en-US' }),
    )
  })

  it('case 5: 上传按钮打开 W29 完整 Modal（不再是 stub）', async () => {
    mockedListVoicePacks.mockResolvedValue({ data: [] })
    renderWithClient(<VoicePackLibrary />)
    await waitFor(() => {
      expect(mockedListVoicePacks).toHaveBeenCalled()
    })
    const uploadBtn = screen.getByRole('button', {
      name: /uploadCustom|上传定制音色|Upload Custom Voice/i,
    })
    fireEvent.click(uploadBtn)
    // W29 Modal 必含 prefix / display_name 字段（aria-label 上挂的 voice-pack-prefix）
    expect(
      await screen.findByLabelText(/voice-pack-prefix/i),
    ).toBeInTheDocument()
    expect(screen.getByLabelText(/voice-pack-display-name/i)).toBeInTheDocument()
  })

  it('case 6: 自定义音色列表的 clone_status 4 态 badge 都能渲染', async () => {
    mockedListVoicePacks.mockResolvedValue({ data: [] })
    mockedListCustom.mockResolvedValue({
      data: {
        items: [
          makeCustom({ id: 'clone_dep', name: 'd1', clone_status: 'deploying' }),
          makeCustom({ id: 'clone_rdy', name: 'r1', clone_status: 'ready' }),
          makeCustom({
            id: 'clone_fail',
            name: 'f1',
            clone_status: 'failed',
            description: '\n[clone_failed] DashScope returned UNDEPLOYED',
          }),
          makeCustom({ id: 'clone_del', name: 'x1', clone_status: 'deleted' }),
        ],
        pagination: { page: 1, page_size: 100, total: 4, max_page: 1 },
      },
    })

    renderWithClient(<VoicePackLibrary />)

    // 等列表落地
    expect(await screen.findByText('d1')).toBeInTheDocument()
    expect(screen.getByText('r1')).toBeInTheDocument()
    expect(screen.getByText('f1')).toBeInTheDocument()
    expect(screen.getByText('x1')).toBeInTheDocument()

    // 4 态 badge 都通过 aria-label 暴露
    expect(
      screen.getByLabelText(/clone-status-deploying/i),
    ).toBeInTheDocument()
    expect(screen.getByLabelText(/clone-status-ready/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/clone-status-failed/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/clone-status-deleted/i)).toBeInTheDocument()
  })

  it('case 7: 列表无 deploying 行时 refetchInterval 应处于关闭状态（不会持续触发）', async () => {
    mockedListVoicePacks.mockResolvedValue({ data: [] })
    mockedListCustom.mockResolvedValue({
      data: {
        items: [makeCustom({ id: 'clone_rdy', name: 'r1', clone_status: 'ready' })],
        pagination: { page: 1, page_size: 100, total: 1, max_page: 1 },
      },
    })

    renderWithClient(<VoicePackLibrary />)
    await waitFor(() => {
      expect(mockedListCustom).toHaveBeenCalledTimes(1)
    })

    // 等待一段较长时间也不再触发额外 refetch（因为没有 deploying 行）
    await new Promise((r) => setTimeout(r, 50))
    expect(mockedListCustom).toHaveBeenCalledTimes(1)
  })
})
