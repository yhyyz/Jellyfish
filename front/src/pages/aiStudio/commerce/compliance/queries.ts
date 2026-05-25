/**
 * 合规中心 (ComplianceCenter) 页面的 TanStack Query hooks。
 *
 * 仅暴露只读查询：
 * - `useComplianceProfileList` 拉取系统预置 profile 列表（默认 3 条：
 *   `cn_mainland_default` / `cn_mainland_health` / `overseas_default`）。
 * - `useComplianceProfileDetail` 拉取单个 profile 的完整 rules JSON，
 *   供「规则浏览」Tab 做只读 JSON 展示。
 * - `useComplianceFindingList` 按 variant_id (+ 可选 severity) 拉取 finding
 *   历史；后端要求 `variant_id` 必填，因此未输入时本 hook 自动 disabled。
 *
 * 设计要点：
 * - 直接调用 generated `StudioComplianceService`，遵循 AGENTS.md 第 2 条
 *   ——前端不再新增手写 service 封装。
 * - P1 阶段写入接口（profile CRUD / finding 标记解决）暂未对外暴露，
 *   故本文件刻意不提供 useMutation；任何写操作请等到 P3 后再开放。
 * - query key factory 采用元组形式，方便后续 `invalidateQueries` 精准失效。
 */
import { useQuery } from '@tanstack/react-query'
import { StudioComplianceService } from '../../../../services/generated'
import type {
  ComplianceFindingRead,
  ComplianceProfileRead,
} from '../../../../services/generated'

/**
 * Query key factory —— 与同模块其他 commerce 页面保持元组形态一致。
 *
 * - `profiles()`：profile 列表 key（不带过滤参数，列表数据极小）。
 * - `profile(id)`：单个 profile 详情 key。
 * - `findings(variantId, severity)`：finding 列表 key；缺省值统一序列化为
 *   `'all'`，避免 `undefined` 进入 key 造成命中歧义。
 */
export const complianceKeys = {
  profiles: () => ['commerce', 'compliance', 'profiles'] as const,
  profile: (id: string) => ['commerce', 'compliance', 'profile', id] as const,
  findings: (variantId?: string, severity?: string) =>
    [
      'commerce',
      'compliance',
      'findings',
      variantId ?? 'all',
      severity ?? 'all',
    ] as const,
}

/**
 * 拉取系统预置合规 profile 列表（不分页）。
 *
 * 当前后端默认返回 3 条系统 profile，规模极小，因此前端不做地域过滤，
 * 由调用方在 UI 层按 `region` 字段分组渲染。响应壳兜底为空数组，
 * 避免后续 `.map` 报错。
 */
export function useComplianceProfileList() {
  return useQuery<ComplianceProfileRead[]>({
    queryKey: complianceKeys.profiles(),
    queryFn: async () => {
      const res =
        await StudioComplianceService.listComplianceProfilesApiV1StudioComplianceProfilesGet(
          {},
        )
      return res.data ?? []
    },
  })
}

/**
 * 拉取单个 profile 详情（含完整 `rules` JSON 数组）。
 *
 * 仅在用户主动选中某个 profile 进入「规则浏览」Tab 时启用，避免列表 Tab
 * 默认就为每个 profile 拉一份重复数据。`id` 为空时 hook disabled。
 */
export function useComplianceProfileDetail(id: string | null | undefined) {
  return useQuery<ComplianceProfileRead | null>({
    queryKey: complianceKeys.profile(id ?? ''),
    enabled: !!id,
    queryFn: async () => {
      if (!id) return null
      const res =
        await StudioComplianceService.getComplianceProfileApiV1StudioComplianceProfilesProfileIdGet(
          { profileId: id },
        )
      return res.data ?? null
    },
  })
}

/**
 * 按 variant_id 拉取合规 finding 历史。
 *
 * 后端将 `variant_id` 作为必填查询参数，因此当上层未提供该值时，
 * 本 hook 自动 disabled，UI 层据此提示「请输入 variant_id」。
 *
 * @param variantId 变体 ID（必填，缺省时不发请求）。
 * @param severity  可选严重度过滤：`info` / `warning` / `blocker`；
 *                  传入 `'all'` 或 `undefined` 表示不过滤。
 */
export function useComplianceFindingList(
  variantId?: string,
  severity?: string,
) {
  const enabled = !!variantId && variantId.trim().length > 0
  const normalizedSeverity =
    severity && severity !== 'all' ? severity : undefined
  return useQuery<ComplianceFindingRead[]>({
    queryKey: complianceKeys.findings(variantId, severity),
    enabled,
    queryFn: async () => {
      if (!variantId) return []
      const res =
        await StudioComplianceService.listComplianceFindingsApiV1StudioComplianceFindingsGet(
          {
            variantId,
            severity: normalizedSeverity ?? null,
          },
        )
      return res.data ?? []
    },
  })
}
