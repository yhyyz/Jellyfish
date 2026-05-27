/**
 * colorCodec 单元测试。
 *
 * 覆盖 ASS 字幕颜色字面量与 web hex 之间的互转：
 * - ASS 内部按 alpha + BGR 字节序排列（`&HAABBGGRR`），跟 web 的 `#RRGGBB` 字节序相反。
 * - 默认 alpha 为 `00`（完全不透明）。
 * - 非法 hex 必须显式抛 Error，不允许静默 fallback（避免上游误把脏数据
 *   传到字幕渲染管线）。
 */
import { describe, it, expect } from 'vitest'
import { toAss, fromAss } from '../colorCodec'

describe('colorCodec.toAss', () => {
  it('把 #FF8800 转成 &H000088FF (00 alpha + BGR 字节序)', () => {
    // 红黄色 → ASS 字面量：alpha=00、B=00、G=88、R=FF
    expect(toAss('#FF8800')).toBe('&H000088FF')
  })

  it('不带 # 前缀的 hex 也接受并自动补 #', () => {
    expect(toAss('FF8800')).toBe('&H000088FF')
  })

  it('非法 hex 抛 Error（不静默 fallback）', () => {
    expect(() => toAss('not-a-hex')).toThrow(/invalid hex/i)
    expect(() => toAss('#GGG')).toThrow(/invalid hex/i)
  })
})

describe('colorCodec.fromAss', () => {
  it('把 &H000088FF 还原为 #FF8800（去 alpha + 倒序 BGR→RGB）', () => {
    expect(fromAss('&H000088FF')).toBe('#FF8800')
  })
})

describe('colorCodec roundtrip', () => {
  it('任意合法 hex 经 toAss → fromAss 恒等', () => {
    const samples = ['#000000', '#FFFFFF', '#FF8800', '#1A2B3C', '#abcdef']
    for (const hex of samples) {
      const ass = toAss(hex)
      const back = fromAss(ass)
      expect(back.toUpperCase()).toBe(hex.toUpperCase())
    }
  })
})
