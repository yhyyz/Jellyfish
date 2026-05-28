/**
 * ConsistencyBadge 单测（W27-T3 TDD）。
 *
 * 覆盖契约：
 *
 * 1. ``score >= 0.85`` → 绿色（status=green，antd Tag color=success）
 * 2. ``0.75 <= score < 0.85`` → 琥珀（status=amber，color=warning）
 * 3. ``score < 0.75`` → 红色（status=red，color=error）
 * 4. ``score === null`` → 灰色（status=unknown，color=default）+ "未评估"文案
 * 5. 提供 onClick 时点击徽章触发 callback，并把 shotId 透传给 handler
 *
 * 阈值与 backend ``shot_consistency_service.SCORE_THRESHOLD_*`` 同源；
 * 任何阈值变更必须同时更新前后端实现 + 本测试。
 */
import { describe, it, expect, vi, beforeAll } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { ConsistencyBadge, deriveConsistencyStatus } from '../ConsistencyBadge'

// antd 的 Tooltip / Tag 在 jsdom 下需要 matchMedia / ResizeObserver 兜底，
// 与 BrandStyleGuideForm.test.tsx 同款 polyfill。
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

describe('ConsistencyBadge', () => {
  it('test_badge_renders_green_for_score_above_85: 高分场景渲染绿色档', () => {
    render(<ConsistencyBadge score={0.92} />)
    const tag = screen.getByTestId('consistency-badge')
    expect(tag.getAttribute('data-status')).toBe('green')
    expect(tag.textContent).toContain('一致性优')
    expect(tag.textContent).toContain('0.92')
  })

  it('test_badge_renders_amber_for_score_75_to_85: 中档分数渲染琥珀色', () => {
    render(<ConsistencyBadge score={0.78} />)
    const tag = screen.getByTestId('consistency-badge')
    expect(tag.getAttribute('data-status')).toBe('amber')
    expect(tag.textContent).toContain('一致性中')
    expect(tag.textContent).toContain('0.78')
  })

  it('test_badge_renders_red_for_score_below_75: 低分场景渲染红色档', () => {
    render(<ConsistencyBadge score={0.5} />)
    const tag = screen.getByTestId('consistency-badge')
    expect(tag.getAttribute('data-status')).toBe('red')
    expect(tag.textContent).toContain('一致性差')
    expect(tag.textContent).toContain('0.50')
  })

  it('test_badge_renders_grey_for_null_score: null 分数渲染灰档（未评估）', () => {
    render(<ConsistencyBadge score={null} />)
    const tag = screen.getByTestId('consistency-badge')
    expect(tag.getAttribute('data-status')).toBe('unknown')
    expect(tag.textContent).toContain('未评估')
    // 不应渲染数值
    expect(tag.textContent).not.toContain('0.00')
  })

  it('test_badge_invokes_onClick_with_shotId: 点击徽章触发 callback 并透传 shotId', () => {
    const handleClick = vi.fn()
    render(<ConsistencyBadge score={0.91} shotId="shot-abc" onClick={handleClick} />)
    const tag = screen.getByTestId('consistency-badge')
    fireEvent.click(tag)
    expect(handleClick).toHaveBeenCalledTimes(1)
    expect(handleClick).toHaveBeenCalledWith('shot-abc')
  })

  it('deriveConsistencyStatus: 边界值 0.85 应判定为 green（>= 阈值）', () => {
    expect(deriveConsistencyStatus(0.85)).toBe('green')
    expect(deriveConsistencyStatus(0.8499)).toBe('amber')
    expect(deriveConsistencyStatus(0.75)).toBe('amber')
    expect(deriveConsistencyStatus(0.7499)).toBe('red')
    expect(deriveConsistencyStatus(null)).toBe('unknown')
    expect(deriveConsistencyStatus(undefined)).toBe('unknown')
    expect(deriveConsistencyStatus(NaN)).toBe('unknown')
  })
})
