/**
 * 公式库 (FormulaLibrary) 页面的 TanStack Query hooks。
 *
 * 提供只读浏览能力：
 * - `useFormulaLibraryList`：按地域过滤拉取系统级剧情公式列表（W11-T1 后总计 12 条）。
 * - `useFormulaLibraryDetail`：按 ID 获取公式完整结构（含 beats / sample_dialog 等重数据）。
 *
 * 设计说明：
 * - 公式库为系统级模板，前端仅读取，不涉及任何 mutation；P2 才会暴露编辑能力。
 * - query key 工厂使用扁平字符串元组，方便后续 invalidate 与调试。
 * - 详情查询通过 `enabled` 配合 `selectedId`，避免空 ID 触发请求。
 */
import { useQuery } from '@tanstack/react-query'
import { StudioStoryFormulasService } from '../../../../services/generated'
import type {
  FormulaRegion,
  StoryFormulaRead,
} from '../../../../services/generated'

/**
 * 公式库相关 query key 工厂。
 * - `list(region)`：按地域过滤的列表缓存键，`undefined` 折叠成 `'all'` 以避免缓存碎片。
 * - `detail(id)`：单条公式详情缓存键，按公式 ID 隔离。
 */
export const formulaLibraryKeys = {
  list: (region?: string) =>
    ['commerce', 'formula-library', 'list', region ?? 'all'] as const,
  detail: (id: string) =>
    ['commerce', 'formula-library', 'detail', id] as const,
}

/**
 * 拉取系统级剧情公式列表。
 *
 * @param region 地域过滤，可选值见 `FormulaRegion`（cn / global）。`undefined` 表示不过滤。
 * @returns TanStack Query 的查询结果，`data` 为公式数组，未命中时为空数组。
 */
export function useFormulaLibraryList(region?: string) {
  return useQuery<StoryFormulaRead[]>({
    queryKey: formulaLibraryKeys.list(region),
    queryFn: async () => {
      const res = await StudioStoryFormulasService.listStoryFormulasApiV1StudioStoryFormulasGet({
        region: (region as FormulaRegion | null | undefined) ?? null,
      })
      return res.data ?? []
    },
  })
}

/**
 * 拉取单条剧情公式详情。
 *
 * @param id 公式 ID（如 `underdog_triumph`）。空字符串将禁用查询。
 * @returns TanStack Query 的查询结果，`data` 为完整 `StoryFormulaRead`。
 *
 * 行为说明：
 * - 仅当 `id` 非空时才会触发请求；调用方通过控制 `selectedId` 来开关详情抽屉。
 * - 后端 404 会抛出 ApiError，由调用方 / 全局错误边界处理。
 */
export function useFormulaLibraryDetail(id: string) {
  return useQuery<StoryFormulaRead>({
    queryKey: formulaLibraryKeys.detail(id),
    queryFn: async () => {
      const res = await StudioStoryFormulasService.getStoryFormulaApiV1StudioStoryFormulasFormulaIdGet({
        formulaId: id,
      })
      if (!res.data) throw new Error('empty formula detail response')
      return res.data
    },
    enabled: !!id,
  })
}
