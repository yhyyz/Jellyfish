/**
 * P2 钩子/CTA/品牌人格选择器 TanStack Query hooks（Wave 13 P2 增强）。
 *
 * 三类系统级"运营资产"（HookPattern / CtaPattern / BrandArchetype）由
 * W14-T4 暴露为只读 GET 接口，本文件提供前端读取入口，供 StoryWorkbench
 * 的 P2 选择器组件（HookPatternSelector / CTASelector /
 * ArchetypeVoiceSlider）消费。
 *
 * 设计要点：
 * - 与 sibling `queries.ts` 解耦（避免与 W8 项目大厅 query keys 冲突），
 *   独立维护 `patternKeys` 命名空间。
 * - 直接调用 OpenAPI 生成的 service，不再做手写 service 包装
 *   （遵循 AGENTS.md 第 2 条）。
 * - 三张表均为系统级种子，规模 ≤12 条，因此不分页、不按需重新拉取，
 *   依赖 React Query 默认缓存即可。
 * - 过滤参数（pattern_type / hardness / urgency_type）下沉到 query key
 *   一部分，确保切换过滤值时各自命中独立缓存。
 */
import { useQuery } from '@tanstack/react-query'
import {
  StudioHookPatternsService,
  StudioCtaPatternsService,
  StudioBrandArchetypesService,
} from '../../../../services/generated'
import type {
  BrandArchetypeRead,
  CtaPatternRead,
  HookPatternRead,
} from '../../../../services/generated'

/**
 * Pattern library query key factory。
 *
 * - hookList：钩子模式列表，按 `patternType` 拆分缓存。
 * - ctaList：CTA 模式列表，按 `{hardness, urgency_type}` 双轴拆分缓存；
 *   稳定 stringify 以避免对象引用不同导致的缓存抖动。
 * - archetypeList：品牌人格列表（无过滤参数）。
 */
export const patternKeys = {
  hookList: (patternType?: string) =>
    ['commerce', 'hook-patterns', patternType ?? 'all'] as const,
  ctaList: (filter?: { hardness?: string; urgency_type?: string }) =>
    [
      'commerce',
      'cta-patterns',
      {
        hardness: filter?.hardness ?? 'all',
        urgency_type: filter?.urgency_type ?? 'all',
      },
    ] as const,
  archetypeList: () => ['commerce', 'brand-archetypes'] as const,
}

/**
 * 拉取钩子模式列表（按 `patternType` 可选过滤）。
 *
 * 后端默认 `sort_order` 升序返回（规模 ≤10 条，不分页）。
 * `patternType` 不传或传空字符串时返回全部钩子。
 */
export function useHookPatternList(patternType?: string) {
  return useQuery<HookPatternRead[]>({
    queryKey: patternKeys.hookList(patternType),
    queryFn: async () => {
      const res = await StudioHookPatternsService.listHookPatternsApiV1StudioHookPatternsGet({
        patternType: patternType ?? null,
      })
      return res.data ?? []
    },
  })
}

/**
 * 拉取 CTA 模式列表（按 `hardness × urgency_type` 双轴可选过滤）。
 *
 * 后端默认 `sort_order` 升序返回（规模 ≤5 条，不分页）。
 * 任一过滤维度为空字符串/未传时按"不过滤该维度"处理。
 */
export function useCtaPatternList(filter: {
  hardness?: string
  urgency_type?: string
}) {
  return useQuery<CtaPatternRead[]>({
    queryKey: patternKeys.ctaList(filter),
    queryFn: async () => {
      const res = await StudioCtaPatternsService.listCtaPatternsApiV1StudioCtaPatternsGet({
        hardness: filter.hardness ?? null,
        urgencyType: filter.urgency_type ?? null,
      })
      return res.data ?? []
    },
  })
}

/**
 * 拉取品牌人格原型列表（无过滤参数，固定 12 条）。
 *
 * 后端默认 `sort_order` 升序返回（规模 ≤12 条，不分页）。
 * 用于 ArchetypeVoiceSlider 的人格下拉选择。
 */
export function useBrandArchetypeList() {
  return useQuery<BrandArchetypeRead[]>({
    queryKey: patternKeys.archetypeList(),
    queryFn: async () => {
      const res = await StudioBrandArchetypesService.listBrandArchetypesApiV1StudioBrandArchetypesGet()
      return res.data ?? []
    },
  })
}
