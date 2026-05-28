/**
 * audit-i18n-completeness.ts
 *
 * 做什么：扫描 front/src/locales/ 下所有 locale，确保 zh-CN 的 key 集合
 *         在 en-US / ja-JP / ko-KR 三个目标 locale 都完整存在。
 *
 * 为什么存在：i18next 缺 key 默认 fallback 到 zh-CN 不抛错，但用户体验是
 *             跨语言混杂（半中半外），P5 W28 整树要求 4 locale 完整对齐。
 *             本脚本作为 CI 守门，单语缺 key 即 exit 1 + 列出所有缺失。
 *
 * 调用方式：pnpm exec tsx front/scripts/audit-i18n-completeness.ts
 *           或: pnpm run audit-i18n（package.json 注册的快捷别名）
 *
 * 退出码：
 *   0 - 4 locale × 5 命名空间所有 leaf key 完全对齐
 *   1 - 至少一个 (locale, namespace) 缺少 reference 中存在的 leaf key
 *
 * 范围：仅比较 leaf key（值为字符串/数字/布尔的最深节点）；
 *       空对象 `{}`（如 P2 占位 ns: compliance/formula/hook/cta/archetype）
 *       不会产生 leaf key，因此不会被审计强制要求填充。
 */

import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

const LOCALES_DIR = path.resolve(__dirname, '../src/locales')
const NAMESPACES = ['common', 'layout', 'settings', 'notFound', 'commerce', 'auth'] as const
const REFERENCE_LOCALE = 'zh-CN'
const TARGET_LOCALES = ['en-US', 'ja-JP', 'ko-KR'] as const

/**
 * 把嵌套对象拍平为 dot.path leaf key 列表。
 * 空对象不会产生 leaf；数组按整体节点处理（不递归进数组元素）。
 */
function flattenKeys(obj: unknown, prefix = ''): string[] {
  if (obj === null || typeof obj !== 'object' || Array.isArray(obj)) {
    return prefix ? [prefix] : []
  }
  const keys: string[] = []
  for (const k of Object.keys(obj as Record<string, unknown>)) {
    const value = (obj as Record<string, unknown>)[k]
    const next = prefix ? `${prefix}.${k}` : k
    if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
      const childKeys = flattenKeys(value, next)
      if (childKeys.length === 0) {
        // 空对象本身不算 leaf，不强制目标 locale 镜像填充
        continue
      }
      keys.push(...childKeys)
    } else {
      keys.push(next)
    }
  }
  return keys
}

let exitCode = 0
const missing: Record<string, string[]> = {}
const refKeyCount: Record<string, number> = {}

for (const ns of NAMESPACES) {
  const refPath = path.join(LOCALES_DIR, REFERENCE_LOCALE, `${ns}.json`)
  if (!fs.existsSync(refPath)) {
    console.error(`MISSING REFERENCE FILE: ${refPath}`)
    exitCode = 1
    continue
  }
  const refJson = JSON.parse(fs.readFileSync(refPath, 'utf-8'))
  const refKeys = new Set(flattenKeys(refJson))
  refKeyCount[ns] = refKeys.size

  for (const locale of TARGET_LOCALES) {
    const tgtPath = path.join(LOCALES_DIR, locale, `${ns}.json`)
    if (!fs.existsSync(tgtPath)) {
      console.error(`MISSING FILE: ${tgtPath}`)
      missing[`${locale}/${ns}.json`] = ['<entire file missing>']
      exitCode = 1
      continue
    }
    const tgtJson = JSON.parse(fs.readFileSync(tgtPath, 'utf-8'))
    const tgtKeys = new Set(flattenKeys(tgtJson))
    const diff = [...refKeys].filter((k) => !tgtKeys.has(k))
    if (diff.length > 0) {
      missing[`${locale}/${ns}.json`] = diff
      exitCode = 1
    }
  }
}

if (exitCode === 0) {
  const total = Object.values(refKeyCount).reduce((a, b) => a + b, 0)
  console.log('OK: all 4 locales fully covered.')
  console.log(`  reference (${REFERENCE_LOCALE}) total leaf keys: ${total}`)
  for (const ns of NAMESPACES) {
    console.log(`    ${ns}: ${refKeyCount[ns] ?? 0}`)
  }
  console.log(`  audited locales: ${[REFERENCE_LOCALE, ...TARGET_LOCALES].join(', ')}`)
} else {
  console.error('MISSING KEYS:')
  for (const [file, keys] of Object.entries(missing)) {
    console.error(`  ${file}:`)
    for (const k of keys) console.error(`    - ${k}`)
  }
}

process.exit(exitCode)
