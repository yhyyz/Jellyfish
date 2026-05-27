/**
 * VoicePackLibrary 页面单测（W20-T5，TDD RED 阶段先行）。
 *
 * 覆盖点：
 * 1. query 返回 N 条 VoicePack 时渲染 N 张卡片；每张卡片显示 name + provider tag
 *    + gender tag + 试听按钮。
 * 2. query loading 时渲染 antd Skeleton 占位骨架。
 * 3. query error 时显示错误 banner + 重试按钮，点击重试后重新拉取并展示成功结果。
 * 4. 工具栏 language 下拉切换 (zh-CN → en-US) 时，会带上新 languageCode 重新查询。
 * 5. 点击「上传定制音色」按钮，打开 modal，模态体内出现「敬请期待」占位文案。
 *
 * Mock CommerceVoicePacksService 同 W20-T2 (vi.spyOn) pattern。
 * 不引入真实 i18n provider，断言时使用 t() 在缺失资源时回退的原始 key。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import {
  CommerceVoicePacksService,
  type VoicePackRead,
} from '../../../../../services/generated'
import { VoicePackLibrary } from '../VoicePackLibrary'

// spyOn 的精确返回类型与 MockInstance<unknown> 之间存在 TS 兼容差，
// 测试内只关心 mock API（mockResolvedValue / mockRejectedValueOnce 等），
// 这里用 any 作为别名故意放宽。
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let mockedListVoicePacks: any

/**
 * 构造 VoicePackRead fixture：默认是系统级 zh-CN 的 cosyvoice 龙小淳。
 */
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

/**
 * 构造一个干净的 QueryClient，关闭 retry 避免错误用例被 retry 拖时间。
 */
function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
}

/**
 * 组合 QueryClientProvider + 渲染。
 */
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
    // jsdom 不实现 HTMLMediaElement.play / pause，逐个测试重建 spy。
    playSpy = vi
      .spyOn(HTMLMediaElement.prototype, 'play')
      .mockImplementation(() => Promise.resolve())
    pauseSpy = vi
      .spyOn(HTMLMediaElement.prototype, 'pause')
      .mockImplementation(() => undefined as unknown as void)
  })

  afterEach(() => {
    mockedListVoicePacks.mockRestore()
    playSpy.mockRestore()
    pauseSpy.mockRestore()
  })

  it('case 1: query 返回 voice pack 数组时渲染对应数量的卡片，每张含 name/provider/gender/play 按钮', async () => {
    const a = makePack({
      id: 'cosy_a',
      name: '龙小淳',
      provider: 'aliyun_cosyvoice',
      gender: 'female',
      sample_file_id: 'file-a',
    })
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

    // 卡片：2 张 listitem，分别带 provider tag + gender tag + play 按钮
    const cards = screen.getAllByRole('listitem')
    expect(cards).toHaveLength(2)

    expect(screen.getByText('aliyun_cosyvoice')).toBeInTheDocument()
    expect(screen.getByText('dashscope')).toBeInTheDocument()
    expect(screen.getByText('female')).toBeInTheDocument()
    expect(screen.getByText('male')).toBeInTheDocument()

    expect(
      screen.getByRole('button', { name: /play 龙小淳/i }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /play Sambert 男声/i }),
    ).toBeInTheDocument()
  })

  it('case 2: query loading 时显示 antd Skeleton', () => {
    // 永不 resolve 的 promise → 持续保持 isLoading=true
    let resolveLoading: ((v: { data: VoicePackRead[] }) => void) | undefined
    mockedListVoicePacks.mockImplementationOnce(
      () =>
        new Promise<{ data: VoicePackRead[] }>((resolve) => {
          resolveLoading = resolve
        }) as unknown as ReturnType<typeof mockedListVoicePacks>,
    )

    const { unmount } = renderWithClient(<VoicePackLibrary />)
    expect(document.querySelector('.ant-skeleton')).toBeInTheDocument()

    // 收尾，避免影响后续用例
    resolveLoading?.({ data: [] })
    unmount()
  })

  it('case 3: query error 时显示错误 banner 与重试按钮，点击重试后展示成功结果', async () => {
    mockedListVoicePacks.mockRejectedValueOnce(new Error('boom'))

    renderWithClient(<VoicePackLibrary />)

    const alert = await screen.findByRole('alert')
    expect(alert).toBeInTheDocument()

    // 准备 retry 后的成功结果
    mockedListVoicePacks.mockResolvedValueOnce({
      data: [makePack({ id: 'after_retry', name: '重试成功' })],
    })

    const retryBtn = screen.getByRole('button', { name: /retry|重试|errorRetry/i })
    fireEvent.click(retryBtn)

    await waitFor(() => {
      expect(mockedListVoicePacks).toHaveBeenCalledTimes(2)
    })
    expect(await screen.findByText('重试成功')).toBeInTheDocument()
  })

  it('case 4: 工具栏 language 下拉切换 (zh-CN → en-US) 触发新查询，调用参数包含新 languageCode', async () => {
    mockedListVoicePacks.mockResolvedValue({
      data: [makePack({ id: 'cosy_a', name: '龙小淳' })],
    })

    renderWithClient(<VoicePackLibrary />)

    // 等首次请求落地
    await waitFor(() => {
      expect(mockedListVoicePacks).toHaveBeenCalledTimes(1)
    })
    expect(mockedListVoicePacks).toHaveBeenLastCalledWith(
      expect.objectContaining({ languageCode: 'zh-CN' }),
    )

    // language 下拉切到 en-US：antd Select 的 combobox role 上挂了 aria-label
    const select = screen.getByRole('combobox', { name: /voice-pack-language/i })
    fireEvent.mouseDown(select)
    // antd 5 的 Select dropdown 会在 listbox + virtual-list 双处渲染同一个 label，
    // 因此 findAllByText 会拿到多个节点；点击 option-content 即可触发选择。
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

  it('case 5: 点击上传定制音色按钮打开 modal，模态体内含「敬请期待」占位文案', async () => {
    mockedListVoicePacks.mockResolvedValue({ data: [] })

    renderWithClient(<VoicePackLibrary />)

    // 等空态出现避免与按钮冲突
    await waitFor(() => {
      expect(mockedListVoicePacks).toHaveBeenCalled()
    })

    const uploadBtn = screen.getByRole('button', {
      name: /uploadCustom|上传定制音色/i,
    })
    fireEvent.click(uploadBtn)

    // antd Modal 渲染到 body，使用 findByText 等异步打开。
    // 测试环境无 i18n provider，t() 回退到 raw key；同时兼容真实中文文案。
    expect(
      await screen.findByText(/敬请期待|voicePackLibrary\.uploadComingSoon/),
    ).toBeInTheDocument()
  })
})
