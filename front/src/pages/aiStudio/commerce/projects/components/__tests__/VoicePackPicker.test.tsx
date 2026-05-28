/**
 * VoicePackPicker 组件单测（W20-T2，TDD RED 阶段先行）。
 *
 * 覆盖点：
 * 1. 仅展示 language_code 与 prop 匹配的 VoicePack 行（防御式过滤）。
 * 2. ≥2 provider 时按 provider 分组渲染。
 * 3. 单 active player：点击新行 play 时上一行 pause。
 * 4. 行点击触发 onChange，并在 value 与 pack.id 匹配时打 aria-selected="true"。
 * 5. 加载中显示 antd Skeleton；错误时显示 Alert 重试 banner。
 *
 * 不引入真实 i18n provider，断言时使用 t() 在缺失资源时回退的原始 key。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import {
  CommerceVoicePacksService,
  type VoicePackRead,
} from '../../../../../../services/generated'
import { VoicePackPicker } from '../VoicePackPicker'

// 尝试过 MockInstance<typeof ...method> 与 ReturnType<typeof vi.spyOn<...>>，
// 但 vitest 2.x 的 MockInstance<T> 约束 T extends (...args: any) => any，
// 而 OpenAPI 生成的方法签名（带可选 options 对象）以及静态类成员的 vi.spyOn
// 第二个泛型参数都无法满足该约束（TS2344）。在 vitest 升级或生成器换型之前
// 保留 any 别名 —— 测试只用 mock API（mockResolvedValue / mockRejectedValueOnce）。
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
 * 构造一个干净的 QueryClient，关闭 retry 避免 RED 用例等 retry。
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

describe('VoicePackPicker', () => {
  let playSpy: ReturnType<typeof vi.spyOn>
  let pauseSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    mockedListVoicePacks = vi.spyOn(
      CommerceVoicePacksService,
      'listVoicePacksEndpointApiV1CommerceVoicePacksGet',
    )
    // jsdom 不实现 HTMLMediaElement.play / pause，逐个测试重建 spy。
    playSpy = vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(() =>
      Promise.resolve(),
    )
    pauseSpy = vi
      .spyOn(HTMLMediaElement.prototype, 'pause')
      .mockImplementation(() => undefined as unknown as void)
  })

  afterEach(() => {
    mockedListVoicePacks.mockRestore()
    playSpy.mockRestore()
    pauseSpy.mockRestore()
  })

  it('仅渲染 language_code 与 prop 匹配的 VoicePack（防御式过滤）', async () => {
    // 模拟后端虽然按 language_code 过滤，但仍掺入了一条 en-US 数据 → 组件应剔除
    const zhPack = makePack({ id: 'cosy_zh', name: '龙小淳', language_code: 'zh-CN' })
    const enPack = makePack({
      id: 'cosy_en',
      name: 'Emma EN',
      language_code: 'en-US',
      sample_file_id: 'file-en',
    })
    mockedListVoicePacks.mockResolvedValue({ data: [zhPack, enPack] })

    renderWithClient(<VoicePackPicker languageCode="zh-CN" onChange={() => {}} />)

    expect(await screen.findByText('龙小淳')).toBeInTheDocument()
    expect(screen.queryByText('Emma EN')).not.toBeInTheDocument()
  })

  it('当 ≥2 个 provider 时按 provider 分组渲染', async () => {
    const cosy = makePack({
      id: 'cosy_a',
      name: '龙小淳',
      provider: 'aliyun_cosyvoice',
      sample_file_id: 'file-a',
    })
    const dashscope = makePack({
      id: 'sambert_a',
      name: 'Sambert 男声',
      provider: 'dashscope',
      sample_file_id: 'file-b',
    })
    mockedListVoicePacks.mockResolvedValue({ data: [cosy, dashscope] })

    renderWithClient(<VoicePackPicker languageCode="zh-CN" onChange={() => {}} />)

    await screen.findByText('龙小淳')
    const groups = screen.getAllByRole('group')
    expect(groups).toHaveLength(2)
    // 分组通过 aria-label 区分 provider
    const labels = groups.map((g) => g.getAttribute('aria-label')).sort()
    expect(labels).toEqual(['aliyun_cosyvoice', 'dashscope'])
  })

  it('单 active player：点击新行 play 时上一行自动 pause', async () => {
    const a = makePack({ id: 'cosy_a', name: '龙小淳', sample_file_id: 'file-a' })
    const b = makePack({ id: 'cosy_b', name: '龙小白', sample_file_id: 'file-b' })
    mockedListVoicePacks.mockResolvedValue({ data: [a, b] })

    renderWithClient(<VoicePackPicker languageCode="zh-CN" onChange={() => {}} />)

    await screen.findByText('龙小淳')

    const playSpy = vi.mocked(HTMLMediaElement.prototype.play)
    const pauseSpy = vi.mocked(HTMLMediaElement.prototype.pause)

    const playBtnA = screen.getByRole('button', { name: /play 龙小淳/i })
    fireEvent.click(playBtnA)
    expect(playSpy).toHaveBeenCalledTimes(1)
    expect(pauseSpy).not.toHaveBeenCalled()

    const playBtnB = screen.getByRole('button', { name: /play 龙小白/i })
    fireEvent.click(playBtnB)
    // 上一行被 pause，新行被 play
    expect(pauseSpy).toHaveBeenCalledTimes(1)
    expect(playSpy).toHaveBeenCalledTimes(2)
  })

  it('点击行（非 play 按钮）触发 onChange，且 value 匹配的行打 aria-selected="true"', async () => {
    const a = makePack({ id: 'cosy_a', name: '龙小淳', sample_file_id: 'file-a' })
    const b = makePack({ id: 'cosy_b', name: '龙小白', sample_file_id: 'file-b' })
    mockedListVoicePacks.mockResolvedValue({ data: [a, b] })

    const onChange = vi.fn()
    const client = makeClient()
    const { rerender } = renderWithClient(
      <VoicePackPicker languageCode="zh-CN" onChange={onChange} />,
      client,
    )

    const firstRow = await screen.findByRole('option', { name: /龙小淳/ })
    expect(firstRow).toHaveAttribute('aria-selected', 'false')

    fireEvent.click(firstRow)
    expect(onChange).toHaveBeenCalledWith('cosy_a')

    rerender(
      <QueryClientProvider client={client}>
        <VoicePackPicker
          value="cosy_a"
          languageCode="zh-CN"
          onChange={onChange}
        />
      </QueryClientProvider>,
    )

    const reSelected = screen.getByRole('option', { name: /龙小淳/ })
    expect(reSelected).toHaveAttribute('aria-selected', 'true')
    // 另一行仍未选中
    const other = screen.getByRole('option', { name: /龙小白/ })
    expect(other).toHaveAttribute('aria-selected', 'false')
  })

  it('加载中显示 antd Skeleton，错误时显示重试 banner（点击 retry 触发 refetch）', async () => {
    // 1) 加载态：mock 一个永不 resolve 的 promise → 渲染时应展示 Skeleton
    let resolveLoading: ((v: { data: VoicePackRead[] }) => void) | undefined
    mockedListVoicePacks.mockImplementationOnce(
      () =>
        new Promise<{ data: VoicePackRead[] }>((resolve) => {
          resolveLoading = resolve
        }) as unknown as ReturnType<typeof mockedListVoicePacks>,
    )

    const { unmount } = renderWithClient(
      <VoicePackPicker languageCode="zh-CN" onChange={() => {}} />,
    )

    expect(document.querySelector('.ant-skeleton')).toBeInTheDocument()

    // 释放挂起的 promise，避免影响后续测试
    resolveLoading?.({ data: [] })
    unmount()

    // 2) 错误态：mock reject → 应显示 antd Alert 与重试按钮
    mockedListVoicePacks.mockReset()
    mockedListVoicePacks.mockRejectedValueOnce(new Error('boom'))

    renderWithClient(<VoicePackPicker languageCode="zh-CN" onChange={() => {}} />)

    const alert = await screen.findByRole('alert')
    expect(alert).toBeInTheDocument()

    // 准备让 retry 后返回成功结果
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
})
