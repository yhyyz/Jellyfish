/**
 * StoryOutcome（投放效果）专属 TanStack Query hooks（W22-T1）。
 *
 * 与 sibling `workbench.queries.ts` 解耦：本文件只承载 outcome CRUD 缓存
 * 编排，避免每次扩展投放复盘能力都改动主工作台 hooks。
 *
 * 设计要点：
 * - 仅做最薄封装；底层调用 `outcomeApi`（见
 *   `front/src/services/commerce/outcomeApi.ts`），后者再走 OpenAPI
 *   generated client，遵循 AGENTS.md 第 2 条。
 * - 列表 query key 含 `variantId`，便于按变体精确失效缓存。
 * - 三类 mutation（create / update / delete）成功后均失效该变体的列表
 *   缓存，避免 UI 与后端状态错位。
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { outcomeApi } from '../../../../services/commerce/outcomeApi'
import type {
  StoryOutcomeCreate,
  StoryOutcomeRead,
  StoryOutcomeUpdate,
} from '../../../../services/commerce/outcomeApi'

/** Outcome query key 工厂；按变体维度组织缓存。 */
export const outcomeKeys = {
  all: ['commerce', 'story-outcomes'] as const,
  list: (variantId: string) => [...outcomeKeys.all, 'list', variantId] as const,
}

/**
 * 拉取某变体下的全部投放效果记录。
 *
 * @param variantId 变体 ID；为空时禁用查询，避免拉取所有变体。
 */
export function useOutcomeList(variantId: string | null | undefined) {
  return useQuery({
    queryKey: outcomeKeys.list(variantId ?? ''),
    enabled: !!variantId,
    queryFn: async (): Promise<StoryOutcomeRead[]> => {
      if (!variantId) return []
      return await outcomeApi.list(variantId)
    },
  })
}

/**
 * 创建一条 outcome；成功后失效对应变体的列表缓存。
 */
export function useCreateOutcome() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: StoryOutcomeCreate): Promise<StoryOutcomeRead> => {
      return await outcomeApi.create(payload)
    },
    onSuccess: (created) => {
      void qc.invalidateQueries({ queryKey: outcomeKeys.list(created.variant_id) })
    },
  })
}

/**
 * 部分更新 outcome；成功后失效对应变体的列表缓存。
 */
export function useUpdateOutcome() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      outcomeId,
      patch,
    }: {
      outcomeId: number
      patch: StoryOutcomeUpdate
    }): Promise<StoryOutcomeRead> => {
      return await outcomeApi.update(outcomeId, patch)
    },
    onSuccess: (updated) => {
      void qc.invalidateQueries({ queryKey: outcomeKeys.list(updated.variant_id) })
    },
  })
}

/**
 * 删除 outcome；调用方需要传入 variantId 以便定向失效缓存。
 */
export function useDeleteOutcome() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      outcomeId,
    }: {
      outcomeId: number
      variantId: string
    }): Promise<void> => {
      await outcomeApi.delete(outcomeId)
    },
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({ queryKey: outcomeKeys.list(vars.variantId) })
    },
  })
}
