import { describe, it, expect } from 'vitest'

import { normalizeApiBase } from '../openapi'

/**
 * v0.7.2 (Manual QA Bug E 修复) 回归测试 —
 *
 * Manual QA 发现 W32-followup-2 加的 VITE_API_BASE_URL 注入逻辑与 generated
 * client 内已有的 /api 前缀重叠，导致请求拼成 http://host/api/api/v1/... 双
 * /api 404。修复策略是末尾 /api 或 /api/ 自动 strip。
 *
 * 这里覆盖三类配置形态，避免回归：
 * - 含 /api 后缀（应 strip）
 * - 含 /api/ 后缀（应 strip）
 * - 不含 /api 后缀（保持原样）
 */
describe('normalizeApiBase', () => {
  it('strips trailing /api so generated client /api prefix does not double up', () => {
    expect(normalizeApiBase('http://127.0.0.1:8088/api')).toBe('http://127.0.0.1:8088')
  })

  it('strips trailing /api/ (with trailing slash) variant', () => {
    expect(normalizeApiBase('http://127.0.0.1:8088/api/')).toBe('http://127.0.0.1:8088')
  })

  it('keeps base URL unchanged when no /api suffix is present', () => {
    expect(normalizeApiBase('http://127.0.0.1:8088')).toBe('http://127.0.0.1:8088')
  })

  it('does not over-strip when /api appears mid-path (e.g. /api-prod)', () => {
    expect(normalizeApiBase('http://host/api-prod')).toBe('http://host/api-prod')
  })

  it('handles https + custom port correctly', () => {
    expect(normalizeApiBase('https://api.example.com:8443/api')).toBe(
      'https://api.example.com:8443'
    )
  })
})
