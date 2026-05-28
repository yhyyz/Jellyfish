/**
 * PlatformExportPresetLibrary 页面单测（W23-T1，P4 Wave A）。
 *
 * 覆盖点：
 * 1. query 返回 N 条预设时渲染 N 张卡片；每张卡片显示 name + platform tag +
 *    画幅 / 时长 / 编码 / 响度 4 项参数标签。
 * 2. query loading 时渲染 antd Skeleton 占位骨架。
 * 3. query error 时显示错误 banner + 重试按钮，点击后重新拉取并展示成功结果。
 * 4. 工具栏 platform 下拉切换（全部 → tiktok）时，会带上新 platform 重新查询。
 * 5. 系统预设右上角显示 `system` 标签。
 *
 * Mock StudioPlatformExportPresetsService 同 VoicePackLibrary 的 vi.spyOn 模式。
 * 不引入真实 i18n provider，断言时使用 t() 在缺失资源时回退的原始 key。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import {
  StudioPlatformExportPresetsService,
  type PlatformExportPresetRead,
} from '../../../../../services/generated'
import { PlatformExportPresetLibrary } from '../PlatformExportPresetLibrary'

// spyOn 的精确返回类型与 MockInstance<unknown> 之间存在 TS 兼容差，
// 这里用 any 作为别名故意放宽，与 VoicePackLibrary.test.tsx 一致。
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let mockedList: any

/**
 * 构造 PlatformExportPresetRead fixture：默认是 douyin_default 系统预设。
 */
function makePreset(
  overrides: Partial<PlatformExportPresetRead> = {},
): PlatformExportPresetRead {
  return {
    id: 'douyin_default',
    name: '抖音默认',
    platform: 'douyin',
    aspect_ratio: '9:16',
    max_duration_sec: 60,
    subtitle_style_id: null,
    voice_pack_id: null,
    watermark_file_id: null,
    sticker_specs: [],
    file_format: 'mp4',
    codec_preset: 'h264_high_4_1',
    loudness_lufs: -16.0,
    is_system: true,
    sort_order: 0,
    description: '抖音竖屏默认预设：9:16 画幅、60 秒上限',
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    ...overrides,
  }
}

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
}

function renderWithClient(
  ui: React.ReactNode,
  client: QueryClient = makeClient(),
) {
  const utils = render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
  )
  return { ...utils, client }
}

describe('PlatformExportPresetLibrary', () => {
  beforeEach(() => {
    mockedList = vi.spyOn(
      StudioPlatformExportPresetsService,
      'listPlatformExportPresetsEndpointApiV1StudioPlatformExportPresetsGet',
    )
  })

  afterEach(() => {
    mockedList.mockRestore()
  })

  it('case 1: query 返回多条预设时渲染对应数量的卡片，含 name/platform tag/参数标签', async () => {
    const a = makePreset({
      id: 'douyin_default',
      name: '抖音默认',
      platform: 'douyin',
    })
    const b = makePreset({
      id: 'tiktok_default',
      name: 'TikTok 默认',
      platform: 'tiktok',
      sort_order: 40,
      loudness_lufs: -14.0,
    })
    mockedList.mockResolvedValue({ data: [a, b] })

    renderWithClient(<PlatformExportPresetLibrary />)

    expect(await screen.findByText('抖音默认')).toBeInTheDocument()
    expect(screen.getByText('TikTok 默认')).toBeInTheDocument()

    const cards = screen.getAllByRole('listitem')
    expect(cards).toHaveLength(2)

    // platform tag 渲染
    expect(screen.getByText('douyin')).toBeInTheDocument()
    expect(screen.getByText('tiktok')).toBeInTheDocument()

    // 4 项参数标签都出现（至少一次）：画幅 / 时长 / 编码 / 响度
    expect(screen.getAllByText(/9:16/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/60s/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/h264_high_4_1/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/-16\.0 LUFS|-14\.0 LUFS/).length).toBeGreaterThan(0)
  })

  it('case 2: query loading 时显示 antd Skeleton', () => {
    let resolveLoading:
      | ((v: { data: PlatformExportPresetRead[] }) => void)
      | undefined
    mockedList.mockImplementationOnce(
      () =>
        new Promise<{ data: PlatformExportPresetRead[] }>((resolve) => {
          resolveLoading = resolve
        }) as unknown as ReturnType<typeof mockedList>,
    )

    const { unmount } = renderWithClient(<PlatformExportPresetLibrary />)
    expect(document.querySelector('.ant-skeleton')).toBeInTheDocument()

    resolveLoading?.({ data: [] })
    unmount()
  })

  it('case 3: query error 时显示错误 banner 与重试按钮，点击重试后展示成功结果', async () => {
    mockedList.mockRejectedValueOnce(new Error('boom'))

    renderWithClient(<PlatformExportPresetLibrary />)

    const alert = await screen.findByRole('alert')
    expect(alert).toBeInTheDocument()

    mockedList.mockResolvedValueOnce({
      data: [makePreset({ id: 'after_retry', name: '重试成功' })],
    })

    const retryBtn = screen.getByRole('button', {
      name: /retry|重试|platformExportPresetLibrary\.retry/,
    })
    fireEvent.click(retryBtn)

    await waitFor(() => {
      expect(mockedList).toHaveBeenCalledTimes(2)
    })
    expect(await screen.findByText('重试成功')).toBeInTheDocument()
  })

  it('case 4: platform 下拉切换 (全部 → tiktok) 触发新查询，调用参数包含 platform=tiktok', async () => {
    mockedList.mockResolvedValue({
      data: [makePreset({ id: 'tiktok_default', name: 'TikTok 默认', platform: 'tiktok' })],
    })

    renderWithClient(<PlatformExportPresetLibrary />)

    await waitFor(() => {
      expect(mockedList).toHaveBeenCalledTimes(1)
    })
    // 首次调用：platform=null
    expect(mockedList).toHaveBeenLastCalledWith(
      expect.objectContaining({ platform: null }),
    )

    const select = screen.getByRole('combobox', {
      name: /platform-export-preset-platform/i,
    })
    fireEvent.mouseDown(select)
    const options = await screen.findAllByText('TikTok')
    const clickable = options.find((el) =>
      el.className.includes('ant-select-item-option-content'),
    )
    expect(clickable).toBeTruthy()
    fireEvent.click(clickable!)

    await waitFor(() => {
      expect(mockedList).toHaveBeenCalledTimes(2)
    })
    expect(mockedList).toHaveBeenLastCalledWith(
      expect.objectContaining({ platform: 'tiktok' }),
    )
  })

  it('case 5: 系统预设卡片显示 `system` 标签；用户预设无该标签', async () => {
    const sysPreset = makePreset({
      id: 'douyin_default',
      name: '系统预设',
      is_system: true,
    })
    const userPreset = makePreset({
      id: 'user_custom',
      name: '用户预设',
      is_system: false,
    })
    mockedList.mockResolvedValue({ data: [sysPreset, userPreset] })

    renderWithClient(<PlatformExportPresetLibrary />)

    expect(await screen.findByText('系统预设')).toBeInTheDocument()
    expect(screen.getByText('用户预设')).toBeInTheDocument()

    // 系统预设卡片范围内必须含 `system` 标签
    const systemCard = screen.getByRole('listitem', { name: '系统预设' })
    expect(systemCard.textContent).toMatch(/system/)

    // 用户预设卡片范围内不应含 `system` 标签
    const userCard = screen.getByRole('listitem', { name: '用户预设' })
    expect(userCard.textContent ?? '').not.toMatch(/system/)
  })
})
