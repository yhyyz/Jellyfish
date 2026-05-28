/**
 * ComplianceCenter 页面 TDD 测试套件（W13 backfill）。
 *
 * P2 合规中心是只读 viewer，含 3 Tab：profiles / findings / rules。
 * 本文件按 W12 backfill 模式补齐 ≥3 条核心契约：
 *
 * 1. profiles Tab 默认渲染 profile 列表，覆盖 id / name / region 字段。
 * 2. findings Tab 在未输入 variant_id 时显示引导提示，且不会发起请求。
 * 3. profiles Tab 的列表展开行能展示 RuleSummaryTable 的核心字段
 *    （rule_id / kind / severity）。
 *
 * 测试基础设施：
 * - 与 BrandStyleGuideForm.test.tsx 保持一致，补 matchMedia +
 *   ResizeObserver；antd Table / Tabs 在 jsdom 下都需要这两个 API。
 */
import React from 'react'
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import {
  StudioComplianceService,
  type ComplianceProfileRead,
} from '../../../../../services/generated'
import ComplianceCenter from '../ComplianceCenter'

// antd matchMedia / ResizeObserver 兜底（同 BrandStyleGuideForm.test.tsx）。
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
let mockedListProfiles: any
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let mockedListFindings: any
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let mockedGetProfile: any

/**
 * 构造 ComplianceProfileRead fixture，覆盖典型 3 profile 数据。
 */
function makeProfile(overrides: Partial<ComplianceProfileRead> = {}): ComplianceProfileRead {
  return {
    id: 'cn_mainland_default',
    name: '中国大陆默认',
    region: 'cn_mainland',
    rules: [
      {
        id: 'banned_phrase_universe_first',
        kind: 'banned_phrase',
        severity: 'blocker',
        description: '禁用「宇宙第一」类极端表达',
      },
    ],
    is_system: true,
    description: '中国大陆默认合规集',
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

describe('ComplianceCenter', () => {
  beforeEach(() => {
    mockedListProfiles = vi.spyOn(
      StudioComplianceService,
      'listComplianceProfilesApiV1StudioComplianceProfilesGet',
    )
    mockedListFindings = vi.spyOn(
      StudioComplianceService,
      'listComplianceFindingsApiV1StudioComplianceFindingsGet',
    )
    mockedGetProfile = vi.spyOn(
      StudioComplianceService,
      'getComplianceProfileApiV1StudioComplianceProfilesProfileIdGet',
    )
  })

  afterEach(() => {
    mockedListProfiles.mockRestore()
    mockedListFindings.mockRestore()
    mockedGetProfile.mockRestore()
  })

  it('case 1: profiles Tab 默认渲染 profile 列表，id / name / region 同时可见', async () => {
    mockedListProfiles.mockResolvedValue({
      data: [
        makeProfile({
          id: 'cn_mainland_default',
          name: '中国大陆默认',
          region: 'cn_mainland',
        }),
        makeProfile({
          id: 'overseas_default',
          name: '海外默认',
          region: 'overseas',
        }),
      ],
    })
    mockedGetProfile.mockResolvedValue({ data: null })

    renderWithClient(<ComplianceCenter />)

    expect(await screen.findByText('cn_mainland_default')).toBeInTheDocument()
    expect(screen.getByText('中国大陆默认')).toBeInTheDocument()
    expect(screen.getByText('overseas_default')).toBeInTheDocument()
    expect(screen.getByText('海外默认')).toBeInTheDocument()

    // region tag 渲染中文
    expect(screen.getByText('中国大陆')).toBeInTheDocument()
    expect(screen.getByText('海外')).toBeInTheDocument()

    // 系统预置 / 类型 列
    const systemTags = screen.getAllByText('系统预置')
    expect(systemTags.length).toBeGreaterThanOrEqual(2)
  })

  it('case 2: findings Tab 在未输入 variant_id 时显示引导提示，且不发请求', async () => {
    mockedListProfiles.mockResolvedValue({ data: [] })
    mockedGetProfile.mockResolvedValue({ data: null })

    renderWithClient(<ComplianceCenter />)

    // 等 Tabs 渲染完毕
    await screen.findByText('规则集 Profile')

    // 切到 findings Tab
    fireEvent.click(screen.getByText('findings 历史'))

    // 引导提示文案（与组件内 Alert message 对齐）
    expect(
      await screen.findByText('请先输入 variant_id 查询合规检测历史'),
    ).toBeInTheDocument()

    // 没输入 variant_id 时：findings 接口不应被调用
    expect(mockedListFindings).not.toHaveBeenCalled()
  })

  it('case 3: profiles Tab 行展开后渲染规则速览（rule_id / kind / severity）', async () => {
    mockedListProfiles.mockResolvedValue({
      data: [
        makeProfile({
          id: 'cn_mainland_default',
          name: '中国大陆默认',
          region: 'cn_mainland',
          rules: [
            {
              id: 'banned_phrase_universe_first',
              kind: 'banned_phrase',
              severity: 'blocker',
              description: '禁用「宇宙第一」类极端表达',
            },
            {
              id: 'required_label_ad',
              kind: 'required_label',
              severity: 'warning',
              description: '广告必须标注',
            },
          ],
        }),
      ],
    })
    mockedGetProfile.mockResolvedValue({ data: null })

    renderWithClient(<ComplianceCenter />)

    // 等列表渲染
    await screen.findByText('cn_mainland_default')

    // 点击展开按钮（antd Table expand 触发器，role="button" 且 aria-label 为 Expand row）
    const expandBtns = await screen.findAllByRole('button', {
      name: /expand row|展开|expand/i,
    })
    fireEvent.click(expandBtns[0])

    // 规则速览表格里能看到具体 rule_id 与 kind 标签
    await waitFor(() => {
      expect(
        screen.getByText('banned_phrase_universe_first'),
      ).toBeInTheDocument()
    })
    expect(screen.getByText('required_label_ad')).toBeInTheDocument()
    // severity 中文标签
    expect(screen.getAllByText('阻断').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('警告').length).toBeGreaterThanOrEqual(1)
  })
})
