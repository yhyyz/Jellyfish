/**
 * 剧情带货项目大厅相关 TanStack Query hooks。
 *
 * 镜像 `aiStudio/project/queries.ts` 的封装风格，但调用 commerce_story
 * 专用的生成式 API：StudioStoryProjectsService（项目 CRUD + 商品挂载）
 * 与 StudioStoryFormulasService（剧情公式只读）。
 *
 * 设计要点：
 * - 仅查询 commerce_story 类型项目（后端已强制过滤），无需在前端再过滤。
 * - 所有变更操作在 onSuccess 后失效相关列表 / 详情缓存，避免 UI 与后端
 *   状态错位。
 * - 直接调用生成的 service，不再额外封装 service 层（遵循 AGENTS.md F4）。
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  StudioStoryProjectsService,
  StudioStoryFormulasService,
} from '../../../../services/generated'
import type {
  FormulaRegion,
  ProjectProductLinkCreate,
  StoryProjectConfigUpdate,
  StoryProjectCreate,
  StoryProjectRead,
  StoryFormulaRead,
} from '../../../../services/generated'

/**
 * 剧情带货项目 query key factory。
 * - all：模块根 key，便于 `invalidateQueries({ queryKey: storyProjectKeys.all })` 清空模块缓存。
 * - list：项目列表；当前后端不分页（规模较小），无入参。
 * - detail：项目详情，含 1:1 CommerceStoryConfig。
 */
export const storyProjectKeys = {
  all: ['commerce', 'story-projects'] as const,
  list: () => [...storyProjectKeys.all, 'list'] as const,
  detail: (id: string) => [...storyProjectKeys.all, 'detail', id] as const,
}

/**
 * 拉取剧情带货项目列表。
 *
 * 后端会强制 `kind=commerce_story` 过滤；返回数据已按 created_at 降序，
 * 前端无需再排序。data 兜底为空数组，避免 `.map` 报错。
 */
export function useStoryProjectList() {
  return useQuery<StoryProjectRead[]>({
    queryKey: storyProjectKeys.list(),
    queryFn: async () => {
      const res = await StudioStoryProjectsService.listStoryProjectsApiV1StudioStoryProjectsGet()
      return res.data ?? []
    },
  })
}

/**
 * 拉取单个剧情带货项目详情（含 CommerceStoryConfig）。
 *
 * 仅当 `id` 非空时启用查询，避免在路由切换瞬间发起无意义请求。
 */
export function useStoryProjectDetail(id: string | null | undefined) {
  return useQuery<StoryProjectRead | null>({
    queryKey: storyProjectKeys.detail(id ?? ''),
    enabled: !!id,
    queryFn: async () => {
      if (!id) return null
      const res = await StudioStoryProjectsService.getStoryProjectApiV1StudioStoryProjectsProjectIdGet({
        projectId: id,
      })
      return res.data ?? null
    },
  })
}

/**
 * 创建剧情带货项目（Project + CommerceStoryConfig 单事务）。
 *
 * 创建成功后失效列表缓存，触发 lobby 立即刷新。
 */
export function useCreateStoryProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: StoryProjectCreate): Promise<StoryProjectRead> => {
      const res = await StudioStoryProjectsService.createStoryProjectApiV1StudioStoryProjectsPost({
        requestBody: body,
      })
      if (!res.data) throw new Error('empty story project create response')
      return res.data
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: storyProjectKeys.list() })
    },
  })
}

/**
 * 更新剧情带货项目配置（仅 CommerceStoryConfig 字段）。
 *
 * 成功后同时失效列表与该项目的详情缓存。
 */
export function useUpdateStoryProjectConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      projectId,
      patch,
    }: {
      projectId: string
      patch: StoryProjectConfigUpdate
    }): Promise<StoryProjectRead> => {
      const res = await StudioStoryProjectsService.updateStoryProjectConfigApiV1StudioStoryProjectsProjectIdConfigPatch(
        { projectId, requestBody: patch },
      )
      if (!res.data) throw new Error('empty story project update response')
      return res.data
    },
    onSuccess: (_, vars) => {
      void qc.invalidateQueries({ queryKey: storyProjectKeys.list() })
      void qc.invalidateQueries({ queryKey: storyProjectKeys.detail(vars.projectId) })
    },
  })
}

/**
 * 为剧情带货项目挂载商品（项目级挂载，不区分章节/镜头）。
 *
 * 成功后失效项目详情缓存（聚合统计可能变化）。
 */
export function useLinkProductToStoryProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      projectId,
      productId,
      body,
    }: {
      projectId: string
      productId: string
      body: ProjectProductLinkCreate
    }) => {
      const res = await StudioStoryProjectsService.linkStoryProjectProductApiV1StudioStoryProjectsProjectIdProductsProductIdPost(
        { projectId, productId, requestBody: body },
      )
      return res.data
    },
    onSuccess: (_, vars) => {
      void qc.invalidateQueries({ queryKey: storyProjectKeys.detail(vars.projectId) })
    },
  })
}

/**
 * 取消剧情带货项目的商品挂载。
 *
 * 成功后失效项目详情缓存。
 */
export function useUnlinkProductFromStoryProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      projectId,
      productId,
    }: {
      projectId: string
      productId: string
    }) => {
      await StudioStoryProjectsService.unlinkStoryProjectProductApiV1StudioStoryProjectsProjectIdProductsProductIdDelete(
        { projectId, productId },
      )
    },
    onSuccess: (_, vars) => {
      void qc.invalidateQueries({ queryKey: storyProjectKeys.detail(vars.projectId) })
    },
  })
}

// ---------- 剧情公式（StoryFormula） ----------

/**
 * 剧情公式 query key factory。
 *
 * 列表 key 含 `region` 入参，便于按地域切换时各自命中缓存而不互相污染。
 */
export const storyFormulaKeys = {
  all: ['commerce', 'story-formulas'] as const,
  list: (region?: string) => [...storyFormulaKeys.all, 'list', region ?? 'all'] as const,
  detail: (id: string) => [...storyFormulaKeys.all, 'detail', id] as const,
}

/**
 * 拉取剧情公式列表。
 *
 * 后端默认按 `sort_order` 升序返回（规模 ≤10 条，不分页）。
 * 当 `region` 传入时仅返回对应地域的公式，否则返回全部。
 */
export function useStoryFormulaList(region?: FormulaRegion) {
  return useQuery<StoryFormulaRead[]>({
    queryKey: storyFormulaKeys.list(region),
    queryFn: async () => {
      const res = await StudioStoryFormulasService.listStoryFormulasApiV1StudioStoryFormulasGet({
        region: region ?? null,
      })
      return res.data ?? []
    },
  })
}

/**
 * 拉取单个剧情公式详情。
 *
 * 仅当 `id` 非空时启用，避免无意义请求。
 */
export function useStoryFormulaDetail(id: string | null | undefined) {
  return useQuery<StoryFormulaRead | null>({
    queryKey: storyFormulaKeys.detail(id ?? ''),
    enabled: !!id,
    queryFn: async () => {
      if (!id) return null
      const res = await StudioStoryFormulasService.getStoryFormulaApiV1StudioStoryFormulasFormulaIdGet({
        formulaId: id,
      })
      return res.data ?? null
    },
  })
}
