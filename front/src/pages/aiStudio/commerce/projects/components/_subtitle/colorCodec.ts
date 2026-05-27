/**
 * ASS 字幕颜色编码工具。
 *
 * ASS（Advanced SubStation Alpha）字幕格式的颜色字面量是
 * `&HAABBGGRR`：
 *   - 高 2 字节为 alpha；ASS 的 alpha 是「不透明度的反向值」，
 *     `00` 表示完全不透明、`FF` 表示完全透明。
 *   - 中间 2 字节为蓝（B）。
 *   - 接着 2 字节为绿（G）。
 *   - 末尾 2 字节为红（R）。
 *
 * 跟 web 习惯的 `#RRGGBB` 字节序刚好相反，因此必须在前后端边界做转换：
 * UI 让用户用 `#RRGGBB` 这种通用 hex 输入颜色，写库 / 渲染前再转
 * 成 ASS 字面量。
 *
 * 设计选择：
 *   - 默认 alpha 一律 `00`（完全不透明）。需要透明度的高级用法另外
 *     扩接口，避免污染主路径语义。
 *   - 非法 hex **抛 Error**，不静默 fallback：上游验证失败的颜色不
 *     允许被静悄悄当成黑色 / 白色塞进字幕渲染管线，否则线上会出现
 *     很难定位的颜色错乱。
 *   - 对外只暴露 `toAss` / `fromAss` 两个纯函数，不维护内部状态。
 */

/** 6 位 hex 的正则，允许大小写。 */
const HEX_RE = /^([0-9a-fA-F]{6})$/

/**
 * 把 web hex 颜色（`#RRGGBB` 或 `RRGGBB`）转成 ASS 字面量
 * `&HAABBGGRR`。
 *
 * @param hex - web 风格的 hex 字符串，可带或不带 `#` 前缀；大小写不敏感。
 * @returns ASS 字幕颜色字面量，alpha 字节固定为 `00`。
 * @throws Error - 当输入不符合 6 位 hex 格式时抛出 `invalid hex` 错误。
 */
export const toAss = (hex: string): string => {
  // 容错：自动剥掉 `#` 前缀；不强制要求带 `#`
  const raw = hex.startsWith('#') ? hex.slice(1) : hex
  if (!HEX_RE.test(raw)) {
    throw new Error(`invalid hex color: ${hex}`)
  }
  const upper = raw.toUpperCase()
  const r = upper.slice(0, 2)
  const g = upper.slice(2, 4)
  const b = upper.slice(4, 6)
  // 字节序倒置：web RGB → ASS BGR；alpha 固定 00（完全不透明）
  return `&H00${b}${g}${r}`
}

/**
 * 把 ASS 字面量 `&HAABBGGRR` 还原回 web hex `#RRGGBB`，
 * **丢弃** alpha 字节（UI 主路径不展示透明度）。
 *
 * @param assLiteral - ASS 颜色字面量，需以 `&H` 开头并跟 8 位 hex。
 * @returns web 风格的 `#RRGGBB`，字母大写。
 * @throws Error - 当输入不符合 `&H` + 8 位 hex 的格式时抛 `invalid ASS literal`。
 */
export const fromAss = (assLiteral: string): string => {
  const match = /^&H([0-9a-fA-F]{8})$/.exec(assLiteral)
  if (!match) {
    throw new Error(`invalid ASS literal: ${assLiteral}`)
  }
  const body = match[1].toUpperCase()
  // 跳过前 2 位 alpha；剩下 6 位是 BGR
  const b = body.slice(2, 4)
  const g = body.slice(4, 6)
  const r = body.slice(6, 8)
  return `#${r}${g}${b}`
}
