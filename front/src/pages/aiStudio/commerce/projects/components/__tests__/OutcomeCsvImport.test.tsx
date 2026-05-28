/**
 * OutcomeCsvImport 组件测试（W22-T2，P4 Wave B 1/11）。
 *
 * TDD 覆盖三类用例（要求 ≥ 3）：
 *
 * 1. test_uploads_file_and_renders_summary：选好文件 + 提交 → 调用
 *    `CommerceOutcomesImportService.importOutcomesCsvApiV1...`，并把
 *    返回的 ImportSummary 渲染到 ``outcome-csv-summary``。
 * 2. test_displays_error_rows_in_table：summary.errors 非空时，``outcome-
 *    csv-error-table`` 出现且条目数 = errors.length。
 * 3. test_disables_submit_for_oversized_file：>5MB 文件 → 提交按钮
 *    disabled，``outcome-csv-oversized-alert`` 出现。
 */
import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

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

const mockImport = vi.fn()
vi.mock('../../../../../../services/generated', () => ({
  CommerceOutcomesImportService: {
    importOutcomesCsvApiV1CommerceOutcomesImportPost: (...args: unknown[]) =>
      mockImport(...args),
  },
}))

import { OutcomeCsvImport } from '../OutcomeCsvImport'

beforeEach(() => {
  mockImport.mockReset()
})

/**
 * 包一层 QueryClientProvider，避免 mutation 抛出 "No QueryClient set"。
 */
function renderWithClient(ui: React.ReactElement) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

/**
 * 模拟选中一个 CSV 文件：直接对 antd Upload 内部的隐藏 ``<input
 * type=file>`` 触发 change 事件。``size`` 参数允许测试构造大文件。
 */
function pickFile(name: string, sizeBytes: number, mime = 'text/csv'): void {
  // antd Upload 渲染的 file input 是隐藏元素；querySelector 直查 DOM。
  const input = document.querySelector('input[type="file"]') as HTMLInputElement
  if (!input) throw new Error('upload input not found')
  const blob = new Blob(['header\nrow'], { type: mime })
  const file = new File([blob], name, { type: mime, lastModified: Date.now() })
  // 通过 Object.defineProperty 改写 size 属性，避开真的写一个 6MB 字符串。
  Object.defineProperty(file, 'size', { value: sizeBytes, configurable: true })
  Object.defineProperty(input, 'files', { value: [file], configurable: true })
  fireEvent.change(input)
}

describe('OutcomeCsvImport', () => {
  it('case 1: 上传文件并提交后渲染 ImportSummary', async () => {
    mockImport.mockResolvedValue({
      data: {
        total_rows: 3,
        inserted: 3,
        failed: 0,
        mapping_profile: 'douyin',
        errors: [],
      },
    })

    renderWithClient(<OutcomeCsvImport variantId="var_alpha" />)

    pickFile('outcomes.csv', 1024)
    await userEvent.click(screen.getByTestId('outcome-csv-submit'))

    await waitFor(() => expect(mockImport).toHaveBeenCalledTimes(1), {
      timeout: 3000,
    })
    const callArg = mockImport.mock.calls[0][0] as {
      formData: { file: unknown; mapping_profile: string }
    }
    expect(callArg.formData.mapping_profile).toBe('douyin')

    const summary = await screen.findByTestId('outcome-csv-summary')
    expect(summary).toHaveTextContent('3') // inserted=3
    expect(summary).toHaveTextContent('douyin')
  })

  it('case 2: errors 非空时渲染失败行表格，条目数与 errors 一致', async () => {
    mockImport.mockResolvedValue({
      data: {
        total_rows: 3,
        inserted: 1,
        failed: 2,
        mapping_profile: 'douyin',
        errors: [
          {
            row_index: 2,
            raw_row: { variant_id: '', plays: '100' },
            reason: 'variant_id 不能为空',
          },
          {
            row_index: 4,
            raw_row: { variant_id: 'var_alpha', plays: 'abc' },
            reason: "invalid literal for int(): 'abc'",
          },
        ],
      },
    })

    renderWithClient(<OutcomeCsvImport variantId="var_alpha" />)

    pickFile('outcomes.csv', 2048)
    await userEvent.click(screen.getByTestId('outcome-csv-submit'))

    const errTable = await screen.findByTestId('outcome-csv-error-table')
    expect(errTable).toBeInTheDocument()
    // antd Table 行 = thead 1 + tbody 2 个数据行；用 tbody tr 计数。
    const rows = errTable.querySelectorAll('tbody tr.ant-table-row')
    expect(rows.length).toBe(2)
    expect(errTable).toHaveTextContent('variant_id 不能为空')
  })

  it('case 3: 文件超过 5MB → 提交按钮 disabled + 警示横幅出现', async () => {
    renderWithClient(<OutcomeCsvImport variantId="var_alpha" />)

    pickFile('big.csv', 6 * 1024 * 1024)

    await waitFor(() => {
      const alert = screen.queryByTestId('outcome-csv-oversized-alert')
      expect(alert).toBeInTheDocument()
    })

    const submit = screen.getByTestId('outcome-csv-submit')
    expect(submit).toBeDisabled()

    // 即便点击也不应该触发上传。
    await userEvent.click(submit)
    expect(mockImport).not.toHaveBeenCalled()
  })
})
