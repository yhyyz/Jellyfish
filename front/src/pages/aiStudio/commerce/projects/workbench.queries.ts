/**
 * StoryWorkbench (剧情工作台) 专属 TanStack Query hooks。
 *
 * 与 sibling `queries.ts`（W8-T2 创建，封装项目大厅 CRUD + 公式只读）
 * 解耦：本文件只承载工作台运行期才需要的查询/变更：
 *
 * - StoryVariant 列表与手动创建（P1 fallback：LLM 链路尚未串通时人工录入）
 * - CommerceTasksService 上 commerce/script-generate / compliance/check 入队
 * - 合规 finding 列表（按 variant_id 过滤）
 *
 * 设计要点：
 * - 仅做最薄封装，不再二次定义 service 层；遵循 AGENTS.md 第 2 条。
 * - 所有 mutation 在 onSuccess 后失效相关列表 / 详情缓存，避免 UI 与
 *   后端状态错位。
 * - P1 不做任务轮询（P2 才上 task center 实时刷新），mutation 拿到
 *   `task_id` 后由调用方 `message.success` 提示用户稍后刷新即可。
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CommerceSubtitleStylesService,
  CommerceTasksService,
  CommerceVoicePacksService,
  StudioComplianceService,
  StudioStoryVariantsService,
} from '../../../../services/generated'
import type {
  ComplianceCheckRequest,
  ComplianceFindingRead,
  ScriptGenerateRequest,
  StoryVariantCloneRequest,
  StoryVariantCreate,
  StoryVariantRead,
  StoryVariantStatus,
  SubtitleStyleRead,
  TaskEnqueueResponse,
  VoicePackRead,
} from '../../../../services/generated'

// ---------- StoryVariant ----------

/**
 * 故事变体（StoryVariant）query key factory。
 *
 * 列表 key 含 `projectId` / `chapterId` / `status`，便于按维度切换缓存。
 */
export const storyVariantKeys = {
  all: ['commerce', 'story-variants'] as const,
  list: (projectId: string, chapterId?: string | null, status?: StoryVariantStatus | null) =>
    [...storyVariantKeys.all, 'list', projectId, chapterId ?? null, status ?? null] as const,
}

/**
 * 拉取项目下的故事变体列表。
 *
 * 后端按 `created_at desc` 返回；data 兜底空数组，避免 `.map` 报错。
 * 仅当 `projectId` 非空时启用查询，避免在路由切换瞬间发起无意义请求。
 */
export function useStoryVariants(
  projectId: string | null | undefined,
  chapterId?: string | null,
  status?: StoryVariantStatus | null,
) {
  return useQuery({
    queryKey: storyVariantKeys.list(projectId ?? '', chapterId ?? null, status ?? null),
    enabled: !!projectId,
    queryFn: async (): Promise<StoryVariantRead[]> => {
      if (!projectId) return []
      const res = await StudioStoryVariantsService.listStoryVariantsApiV1StudioStoryVariantsGet({
        projectId,
        chapterId: chapterId ?? null,
        status: status ?? null,
      })
      return res.data ?? []
    },
  })
}

/**
 * 手动创建变体（P1 fallback）。
 *
 * 当 LLM 生成链路暂未可用时，运营/开发可通过该入口直接录入剧本草稿，
 * 进入工作台进行后续合规校验、关键帧生成等流程。
 *
 * 成功后失效该项目下的变体列表缓存以触发 refetch。
 */
export function useCreateStoryVariant() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: StoryVariantCreate): Promise<StoryVariantRead> => {
      const res = await StudioStoryVariantsService.createStoryVariantApiV1StudioStoryVariantsPost({
        requestBody: body,
      })
      if (!res.data) throw new Error('empty story variant response')
      return res.data
    },
    onSuccess: (variant) => {
      void qc.invalidateQueries({ queryKey: [...storyVariantKeys.all, 'list', variant.project_id] })
    },
  })
}

/**
 * 克隆变体（W14-T3，A/B 派生）。
 *
 * 调用 `POST /story-variants/{variant_id}/clone`：基于源变体生成一个新的
 * `draft` 变体，可选覆盖 `archetype` / `hook_pattern_id` / `cta_pattern_id` /
 * `formula_id` / `label` 等 A/B 维度。
 *
 * 成功后失效全部变体列表缓存（不区分 projectId / chapterId / status），
 * 因为新增项可能落在任意分组的列表里。
 */
export function useCloneStoryVariant() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      variantId,
      body,
    }: {
      variantId: string
      body: StoryVariantCloneRequest
    }) => {
      const res = await StudioStoryVariantsService.cloneVariantApiV1StudioStoryVariantsVariantIdClonePost({
        variantId,
        requestBody: body,
      })
      return res.data
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: storyVariantKeys.all })
    },
  })
}

/**
 * 标记冠军变体（W14-T3，同 (project, chapter) 单选）。
 *
 * 调用 `PATCH /story-variants/{variant_id}/champion`：将目标变体置为冠军，
 * 后端会同步取消同章节其它变体的冠军标记。
 *
 * 成功后失效变体列表缓存以触发列表重新拉取，让 UI 上的「Champion」标签
 * 与服务端状态保持一致。
 */
export function useMarkVariantChampion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (variantId: string) => {
      const res = await StudioStoryVariantsService.markVariantChampionApiV1StudioStoryVariantsVariantIdChampionPatch({
        variantId,
      })
      return res.data
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: storyVariantKeys.all })
    },
  })
}

// ---------- Commerce 异步任务入队 ----------

/**
 * 入队“剧情脚本生成”异步任务（POST /commerce/script-generate）。
 *
 * P1 阶段仅负责入队 + 返回 task_id，前端不做轮询。
 * 调用方拿到 `task_id` 后通常以 message.success 提示，并提示用户稍后刷新变体列表。
 */
export function useTriggerScriptGenerate() {
  return useMutation({
    mutationFn: async (body: ScriptGenerateRequest): Promise<TaskEnqueueResponse> => {
      const res = await CommerceTasksService.enqueueScriptGenerateApiV1CommerceScriptGeneratePost({
        requestBody: body,
      })
      if (!res.data) throw new Error('empty script-generate enqueue response')
      return res.data
    },
  })
}

/**
 * 入队“合规检查”异步任务（POST /commerce/compliance/check）。
 *
 * P1 阶段仅负责入队 + 返回 task_id，前端不做轮询。
 * 调用方拿到 `task_id` 后通常以 message.success 提示，并提示用户稍后刷新 findings 列表。
 */
export function useTriggerComplianceCheck() {
  return useMutation({
    mutationFn: async (body: ComplianceCheckRequest): Promise<TaskEnqueueResponse> => {
      const res = await CommerceTasksService.enqueueComplianceCheckApiV1CommerceComplianceCheckPost({
        requestBody: body,
      })
      if (!res.data) throw new Error('empty compliance-check enqueue response')
      return res.data
    },
  })
}

// ---------- 合规 finding ----------

/**
 * 合规 finding query key factory。
 */
export const complianceFindingKeys = {
  all: ['commerce', 'compliance-findings'] as const,
  list: (variantId: string) => [...complianceFindingKeys.all, 'list', variantId] as const,
}

/**
 * 拉取某个变体的合规 findings 列表。
 *
 * 仅当 `variantId` 非空时启用查询；data 兜底空数组。
 * P1 不传 severity / isResolved 过滤，由前端组件按 severity 分组展示。
 */
export function useComplianceFindings(variantId: string | null | undefined) {
  return useQuery({
    queryKey: complianceFindingKeys.list(variantId ?? ''),
    enabled: !!variantId,
    queryFn: async (): Promise<ComplianceFindingRead[]> => {
      if (!variantId) return []
      const res = await StudioComplianceService.listComplianceFindingsApiV1StudioComplianceFindingsGet({
        variantId,
      })
      return res.data ?? []
    },
  })
}

// ---------- VoicePack ----------

/**
 * VoicePack query key factory（W20-T2）。
 *
 * key 携带 languageCode，使不同语言的列表彼此独立缓存。
 */
export const voicePackKeys = {
  all: ['commerce', 'voice-packs'] as const,
  list: (languageCode: string) =>
    [...voicePackKeys.all, 'list', { languageCode }] as const,
}

/**
 * 拉取指定语言下的 VoicePack 列表（W20-T2）。
 *
 * 直接调 OpenAPI 生成的 CommerceVoicePacksService（AGENTS.md 规则 #2）。
 * 仅当 `languageCode` 非空时启用查询，避免空请求。data 兜底空数组。
 */
export function useVoicePacks(languageCode: string | null | undefined) {
  return useQuery({
    queryKey: voicePackKeys.list(languageCode ?? ''),
    enabled: !!languageCode,
    queryFn: async (): Promise<VoicePackRead[]> => {
      if (!languageCode) return []
      const res =
        await CommerceVoicePacksService.listVoicePacksEndpointApiV1CommerceVoicePacksGet({
          languageCode,
        })
      return res.data ?? []
    },
  })
}

// ---------- 字幕样式（W20-T3） ----------

/**
 * 字幕样式 query key factory。
 *
 * 列表 key 含 `isSystem` / `format` / `projectId` 三维度筛选，跟后端
 * `GET /api/v1/commerce/subtitle-styles` 入参一一对应；
 * 任意一项变化都会拿到独立缓存槽，避免 system / 自定义 / 不同格式之
 * 间的列表互相串味。
 */
export const subtitleStyleKeys = {
  all: ['commerce', 'subtitle-styles'] as const,
  list: (
    isSystem: boolean | null,
    format: string | null,
    projectId: string | null,
  ) =>
    [...subtitleStyleKeys.all, 'list', isSystem, format, projectId] as const,
}

/**
 * 字幕样式过滤器入参（与后端 listSubtitleStyles* 路由一一对应）。
 *
 * - `isSystem=true` 仅取 W18 已 seed 的系统模板
 * - `isSystem=false` 仅取用户自定义样式
 * - 缺省时（undefined / null）返回全部
 */
export interface UseSubtitleStylesArgs {
  isSystem?: boolean | null
  format?: string | null
  projectId?: string | null
}

/**
 * 拉取字幕样式列表（W20-T3 SubtitleStylePicker 使用）。
 *
 * 仅做最薄封装：调用 OpenAPI generated client 上的
 * `CommerceSubtitleStylesService.listSubtitleStylesEndpointApiV1CommerceSubtitleStylesGet`，
 * 把响应里的 `data` 兜底成空数组返回，避免 UI 直接 `.map(undefined)` 报错。
 *
 * 不在 hook 里再二次过滤，所有筛选条件原样下传后端，靠 query key 区分缓存。
 */
export function useSubtitleStyles(args: UseSubtitleStylesArgs = {}) {
  const { isSystem = null, format = null, projectId = null } = args
  return useQuery({
    queryKey: subtitleStyleKeys.list(isSystem, format, projectId),
    queryFn: async (): Promise<SubtitleStyleRead[]> => {
      const res =
        await CommerceSubtitleStylesService.listSubtitleStylesEndpointApiV1CommerceSubtitleStylesGet({
          isSystem,
          format,
          projectId,
        })
      return res.data ?? []
    },
  })
}
