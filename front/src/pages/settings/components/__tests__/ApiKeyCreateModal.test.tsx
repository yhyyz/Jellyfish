/**
 * ApiKeyCreateModal 单测（W24-T5，P4 Wave B 7/11）。
 *
 * 聚焦 Modal 自身的核心契约（与 ApiKeysPage 集成测试形成互补）：
 *
 *  1. 提交表单 → 调用注入的 ``onCreate``，并把返回的 ``ApiKeyCreated``
 *     通过 ``onCreated`` 回传给父组件；reveal 阶段 plaintext 可见。
 *  2. 复制按钮：调用 ``navigator.clipboard.writeText`` 写入完整明文。
 */
import React from 'react'
import { describe, it, expect, vi, beforeAll } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import ApiKeyCreateModal from '../ApiKeyCreateModal'
import type { ApiKeyCreated } from '../../../../services/generated'

void React

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

const FAKE_CREATED: ApiKeyCreated = {
  plaintext_key: 'pk_test_ONCE_ONLY_PLAIN_TEXT_value',
  api_key_hash: 'h_unit_aaaa1111bbbb2222',
  description: 'unit-test',
  daily_limit: 10,
  monthly_limit: 100,
  rate_per_minute: 30,
  is_active: true,
  created_at: '2026-05-28T01:00:00Z',
}

describe('ApiKeyCreateModal', () => {
  it('case 1: form submit → onCreate is called and reveal stage shows plaintext', async () => {
    const onCreate = vi.fn(async (_req: unknown) => FAKE_CREATED)
    const onCreated = vi.fn()
    const onCancel = vi.fn()

    render(
      <ApiKeyCreateModal
        open
        onCancel={onCancel}
        onCreated={onCreated}
        onCreate={onCreate}
      />,
    )

    fireEvent.click(await screen.findByTestId('create-api-key-submit'))

    await waitFor(() => {
      expect(onCreate).toHaveBeenCalledTimes(1)
    })

    // 默认值合理（非 undefined），且 description 至少作为字段透传
    const callArg = onCreate.mock.calls[0][0]
    expect(callArg).toHaveProperty('daily_limit')
    expect(callArg).toHaveProperty('monthly_limit')

    // reveal 阶段
    const reveal = await screen.findByTestId('api-key-reveal')
    expect(reveal.textContent).toContain('pk_test_ONCE_ONLY_PLAIN_TEXT_value')
    expect(onCreated).toHaveBeenCalledWith(FAKE_CREATED)
  })

  it('case 2: copy button writes plaintext to clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })

    const onCreate = vi.fn(async () => FAKE_CREATED)
    render(
      <ApiKeyCreateModal
        open
        onCancel={vi.fn()}
        onCreated={vi.fn()}
        onCreate={onCreate}
      />,
    )

    fireEvent.click(await screen.findByTestId('create-api-key-submit'))
    await screen.findByTestId('api-key-reveal')

    fireEvent.click(screen.getByTestId('copy-plaintext-btn'))

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(FAKE_CREATED.plaintext_key)
    })
  })
})
