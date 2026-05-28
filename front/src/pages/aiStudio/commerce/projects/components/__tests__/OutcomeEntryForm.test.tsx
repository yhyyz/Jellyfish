/**
 * OutcomeEntryForm 组件测试（W22-T1，P4 Wave A 1/6）。
 *
 * TDD 覆盖三类用例（要求 ≥ 3）：
 *
 * 1. test_form_calls_api_with_normalized_payload：填写表单后提交，调用
 *    `outcomeApi.create` 时 payload 中的 platform / plays /
 *    completion_rate_3s / gmv 与录入数值一致；recorded_at 序列化为 ISO
 *    字符串。
 * 2. test_form_disables_submit_while_pending：mutation isPending 时提交按
 *    钮 loading + disabled，避免重复提交。
 * 3. test_form_validates_required_fields：gmv 设为负值触发校验，不调后端。
 */
import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

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

const mockMutateAsync = vi.fn()
const mockUseCreateOutcome = vi.fn()
vi.mock('../../outcome.queries', () => ({
  useCreateOutcome: (...args: unknown[]) => mockUseCreateOutcome(...args),
}))

import { OutcomeEntryForm } from '../OutcomeEntryForm'

beforeEach(() => {
  mockMutateAsync.mockReset()
  mockMutateAsync.mockResolvedValue({ id: 1 })
  mockUseCreateOutcome.mockReset()
  mockUseCreateOutcome.mockReturnValue({
    mutateAsync: mockMutateAsync,
    isPending: false,
  })
})

/**
 * antd InputNumber 在受控模式下，jsdom 通过 fireEvent.change 模拟键入，
 * 再 blur 让组件完成 onChange → 父组件 useState 的写回。
 */
function fillNumber(testId: string, value: string): void {
  const input = screen.getByTestId(testId).querySelector('input') as HTMLInputElement
  fireEvent.change(input, { target: { value } })
  fireEvent.blur(input)
}

describe('OutcomeEntryForm', () => {
  it('case 1: 填写表单后提交，调用 outcomeApi.create 携带规范化 payload', async () => {
    const onSuccess = vi.fn()
    render(<OutcomeEntryForm variantId="var_alpha" onSuccess={onSuccess} />)

    fillNumber('outcome-form-plays', '12345')
    fillNumber('outcome-form-completion-rate-3s', '0.55')
    fillNumber('outcome-form-gmv', '1280.5')

    await userEvent.click(screen.getByTestId('outcome-form-submit'))

    await waitFor(() => expect(mockMutateAsync).toHaveBeenCalledTimes(1), { timeout: 3000 })
    const payload = mockMutateAsync.mock.calls[0][0] as {
      variant_id: string
      plays: number
      completion_rate_3s: number | null
      gmv: number
      recorded_at: string
      platform: string
    }
    expect(payload.variant_id).toBe('var_alpha')
    expect(payload.plays).toBe(12345)
    expect(payload.completion_rate_3s).toBeCloseTo(0.55, 5)
    expect(payload.gmv).toBeCloseTo(1280.5, 5)
    expect(payload.recorded_at).toMatch(/^\d{4}-\d{2}-\d{2}T/)
    expect(payload.platform).toBe('douyin')
    expect(onSuccess).toHaveBeenCalledTimes(1)
  })

  it('case 2: mutation isPending 时提交按钮 loading + disabled，无法重复提交', async () => {
    mockUseCreateOutcome.mockReturnValue({
      mutateAsync: mockMutateAsync,
      isPending: true,
    })

    render(<OutcomeEntryForm variantId="var_alpha" onSuccess={vi.fn()} />)

    const submitBtn = screen.getByTestId('outcome-form-submit')
    expect(submitBtn).toBeDisabled()

    await userEvent.click(submitBtn)
    expect(mockMutateAsync).not.toHaveBeenCalled()
  })

  it('case 3: 必填字段缺失（gmv 设为负数）触发校验，不调后端', async () => {
    render(<OutcomeEntryForm variantId="var_alpha" onSuccess={vi.fn()} />)

    fillNumber('outcome-form-gmv', '-1')
    await userEvent.click(screen.getByTestId('outcome-form-submit'))

    await waitFor(() => {
      expect(mockMutateAsync).not.toHaveBeenCalled()
    })
    expect(screen.getByText(/GMV 必须 ≥ 0/)).toBeInTheDocument()
  })
})
