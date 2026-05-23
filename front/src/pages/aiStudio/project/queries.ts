/**
 * ProjectLobby 页面的 TanStack Query hooks。
 *
 * 封装项目列表查询、创建和删除的缓存管理逻辑，
 * 提供 query key factory 供外部精确失效。
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { StudioProjectsService } from '../../../services/generated'
import type { ProjectCreate, ProjectRead } from '../../../services/generated'

/** Query key factory — 保持 key 结构一致，便于 invalidation */
export const projectKeys = {
  all: ['projects'] as const,
  list: () => [...projectKeys.all, 'list'] as const,
  detail: (id: string) => [...projectKeys.all, 'detail', id] as const,
}

/**
 * 获取项目列表。
 * 一次性拉取前 100 条（当前业务量级足够），后续可按需分页。
 */
export function useProjectList() {
  return useQuery({
    queryKey: projectKeys.list(),
    queryFn: async () => {
      const res = await StudioProjectsService.listProjectsApiV1StudioProjectsGet({
        page: 1,
        pageSize: 100,
      })
      return res.data?.items ?? []
    },
  })
}

/**
 * 创建项目 mutation。
 * 成功后自动失效项目列表缓存以触发 refetch。
 */
export function useCreateProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: ProjectCreate) => {
      const res = await StudioProjectsService.createProjectApiV1StudioProjectsPost({
        requestBody: body,
      })
      if (!res.data) throw new Error('empty project response')
      return res.data as ProjectRead
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: projectKeys.list() })
    },
  })
}

/**
 * 删除项目 mutation。
 * 成功后自动失效项目列表缓存。
 */
export function useDeleteProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (projectId: string) => {
      await StudioProjectsService.deleteProjectApiV1StudioProjectsProjectIdDelete({ projectId })
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: projectKeys.list() })
    },
  })
}
