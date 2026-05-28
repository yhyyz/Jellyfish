/**
 * 投放效果（StoryOutcome）API 薄 wrapper（W22-T1，P4 Wave A 1/6）。
 *
 * 严守 AGENTS.md 第 2 条：前端调用后端接口统一走 OpenAPI generated client。
 * 本文件只做"语义化命名"与"返回值解包"两件事，不再二次定义 service：
 *
 * - 把 `CommerceOutcomesService.xxxApiV1CommerceXxxGet` 这种自动生成的冗
 *   长方法名收敛为 `outcomeApi.list / create / update / delete`。
 * - 统一从 `ApiResponse.data` 字段中解包出业务对象，避免每个调用方都
 *   写一遍 `res.data` 兜底。
 *
 * 该 wrapper 不引入业务逻辑或额外缓存层；TanStack Query 的 query/mutation
 * 在 `outcome.queries.ts` 中基于此 wrapper 编排。
 */
import {
  CommerceOutcomesService,
  type StoryOutcomeCreate,
  type StoryOutcomeRead,
  type StoryOutcomeUpdate,
} from '../generated'

export const outcomeApi = {
  /**
   * 列出某变体的全部 outcome 记录（按 recorded_at desc）。
   *
   * @param variantId 变体 ID
   * @returns outcome 列表；空数组表示没有任何投放回传。
   */
  async list(variantId: string): Promise<StoryOutcomeRead[]> {
    const res =
      await CommerceOutcomesService.listOutcomesByVariantApiV1CommerceVariantsVariantIdOutcomesGet({
        variantId,
      })
    return res.data ?? []
  },

  /**
   * 创建一条 outcome 记录；payload 字段语义详见后端 schema。
   *
   * @param payload 创建请求体（已通过前端 antd Form 校验）
   * @returns 服务端回填后的完整 outcome（含自增 id / 时间戳）
   * @throws 当后端返回 4xx/5xx 时抛 ApiError（由调用方统一兜底）。
   */
  async create(payload: StoryOutcomeCreate): Promise<StoryOutcomeRead> {
    const res = await CommerceOutcomesService.createOutcomeApiV1CommerceOutcomesPost({
      requestBody: payload,
    })
    if (!res.data) throw new Error('empty story outcome response')
    return res.data
  },

  /**
   * 部分更新一条 outcome；仅显式传入字段会被覆盖（PATCH 语义）。
   */
  async update(outcomeId: number, patch: StoryOutcomeUpdate): Promise<StoryOutcomeRead> {
    const res = await CommerceOutcomesService.patchOutcomeApiV1CommerceOutcomesOutcomeIdPatch({
      outcomeId,
      requestBody: patch,
    })
    if (!res.data) throw new Error('empty story outcome update response')
    return res.data
  },

  /**
   * 删除一条 outcome；不存在时后端抛 404，由调用方自行处理。
   */
  async delete(outcomeId: number): Promise<void> {
    await CommerceOutcomesService.deleteOutcomeApiV1CommerceOutcomesOutcomeIdDelete({
      outcomeId,
    })
  },
}

export type { StoryOutcomeCreate, StoryOutcomeRead, StoryOutcomeUpdate }
