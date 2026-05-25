/**
 * 商品库 (ProductLibrary) 页面的 TanStack Query hooks。
 *
 * 封装商品列表/创建/更新/删除/图片增删/AI 提取入队等所有交互逻辑，
 * 通过 query key factory 统一管理缓存失效，保持与
 * `front/src/pages/aiStudio/project/queries.ts` 一致的范式。
 *
 * 注意：后端 ProductRead/ProductImageRead 当前以 `dict_str_any` 形式返回
 *（OpenAPI codegen 暂未导出 ProductRead），因此此处定义本地 TS 类型
 *与后端 `app/schemas/commerce/product.py` 保持字段级对齐。
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CommerceTasksService,
  StudioProductsService,
} from '../../../../services/generated'
import type {
  ProductCreate,
  ProductExtractRequest,
  ProductImageCreate,
  ProductUpdate,
  TaskEnqueueResponse,
} from '../../../../services/generated'

/**
 * 商品图响应（与 backend `ProductImageRead` 对齐）。
 * - `quality_level` / `view_angle` 后端会字符串化枚举，前端按字符串渲染。
 */
export type ProductImageRead = {
  id: number
  product_id: string
  file_id: string | null
  quality_level: string
  view_angle: string
  is_primary: boolean
  width: number | null
  height: number | null
  fmt: string | null
  created_at: string
}

/**
 * 商品响应（与 backend `ProductRead` 对齐）。
 * - 列表接口默认返回空 `images` 数组；详情接口才会 JOIN 查询填充。
 */
export type ProductRead = {
  id: string
  name: string
  brand: string
  category: string
  description: string
  price_anchor: number | null
  sku: string | null
  selling_points: string[]
  pain_points_solved: string[]
  target_audience: Record<string, unknown>
  catchphrases: string[]
  competitor_names: string[]
  health_disclaimer_required: boolean
  visual_style: string
  style: string
  prompt_template_id: string | null
  created_at: string
  updated_at: string
  images: ProductImageRead[]
}

/**
 * 商品列表过滤参数。category/style/visualStyle 透传给后端枚举过滤。
 */
export type ProductListFilter = {
  q?: string
  category?: string
  style?: string
  visualStyle?: string
  page?: number
  pageSize?: number
}

/** Query key factory —— 保持 key 结构一致，便于 invalidation */
export const productKeys = {
  all: ['commerce', 'products'] as const,
  list: (filter?: ProductListFilter) =>
    [...productKeys.all, 'list', filter ?? {}] as const,
  detail: (id: string) => [...productKeys.all, 'detail', id] as const,
}

/**
 * 获取商品分页列表。
 *
 * @param filter 过滤/分页条件；任意字段变更都会触发重新拉取。
 * @returns `{ items, total }` 以及 TanStack Query 状态字段。
 */
export function useProductList(filter: ProductListFilter) {
  return useQuery<{ items: ProductRead[]; total: number }>({
    queryKey: productKeys.list(filter),
    queryFn: async () => {
      const res = await StudioProductsService.listProductsApiV1StudioProductsGet({
        q: filter.q ?? null,
        category: filter.category ?? null,
        style: filter.style ?? null,
        visualStyle: filter.visualStyle ?? null,
        order: 'updated_at',
        isDesc: true,
        page: filter.page ?? 1,
        pageSize: filter.pageSize ?? 12,
      })
      // 后端响应壳：`{ items, pagination: { total } }`，pagination 兜底为 0。
      const data = res.data as
        | { items?: unknown[]; pagination?: { total?: number } }
        | undefined
      return {
        items: ((data?.items ?? []) as unknown as ProductRead[]),
        total: data?.pagination?.total ?? 0,
      }
    },
  })
}

/**
 * 获取单个商品详情（含 images 子集合）。
 * 仅在弹窗或编辑场景按需调用，避免列表页的多余请求。
 */
export function useProductDetail(productId: string | null | undefined) {
  return useQuery({
    queryKey: productId ? productKeys.detail(productId) : ['commerce', 'products', 'detail', 'noop'],
    queryFn: async () => {
      if (!productId) throw new Error('productId is required')
      const res = await StudioProductsService.getProductApiV1StudioProductsProductIdGet({ productId })
      if (!res.data) throw new Error('empty product detail')
      return res.data as unknown as ProductRead
    },
    enabled: !!productId,
  })
}

/**
 * 创建商品 mutation。成功后批量失效 `productKeys.all` 下的列表缓存。
 */
export function useCreateProduct() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: ProductCreate) => {
      const res = await StudioProductsService.createProductApiV1StudioProductsPost({ requestBody: body })
      if (!res.data) throw new Error('empty product response')
      return res.data as unknown as ProductRead
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: productKeys.all })
    },
  })
}

/**
 * 更新商品 mutation。同时失效列表与对应详情缓存。
 */
export function useUpdateProduct() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, body }: { id: string; body: ProductUpdate }) => {
      const res = await StudioProductsService.updateProductApiV1StudioProductsProductIdPatch({
        productId: id,
        requestBody: body,
      })
      if (!res.data) throw new Error('empty product update response')
      return res.data as unknown as ProductRead
    },
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({ queryKey: productKeys.all })
      void qc.invalidateQueries({ queryKey: productKeys.detail(vars.id) })
    },
  })
}

/**
 * 删除商品 mutation。后端 CASCADE 会清理 product_images 与 project_product_links。
 */
export function useDeleteProduct() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (productId: string) => {
      await StudioProductsService.deleteProductApiV1StudioProductsProductIdDelete({ productId })
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: productKeys.all })
    },
  })
}

/**
 * 添加商品图 mutation。
 * 后端在 `(product_id, quality_level, view_angle)` 维度做唯一约束，冲突 → 409。
 */
export function useAddProductImage() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ productId, body }: { productId: string; body: ProductImageCreate }) => {
      const res = await StudioProductsService.addProductImageApiV1StudioProductsProductIdImagesPost({
        productId,
        requestBody: body,
      })
      if (!res.data) throw new Error('empty product image response')
      return res.data as unknown as ProductImageRead
    },
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({ queryKey: productKeys.detail(vars.productId) })
      void qc.invalidateQueries({ queryKey: productKeys.all })
    },
  })
}

/**
 * 删除商品图 mutation。后端校验 image 必须挂在该 product 下，否则 404。
 */
export function useDeleteProductImage() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ productId, imageId }: { productId: string; imageId: number }) => {
      await StudioProductsService.deleteProductImageApiV1StudioProductsProductIdImagesImageIdDelete({
        productId,
        imageId,
      })
    },
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({ queryKey: productKeys.detail(vars.productId) })
      void qc.invalidateQueries({ queryKey: productKeys.all })
    },
  })
}

/**
 * 入队“商品信息抽取”异步任务。
 *
 * P1 阶段仅负责入队 + 返回 task_id，前端不做轮询（P2 再补）。
 * 调用方拿到 `task_id` 后通常以 message.success 提示，并提示用户稍后刷新列表。
 */
export function useExtractProductFromText() {
  return useMutation({
    mutationFn: async (rawText: string): Promise<TaskEnqueueResponse> => {
      const body: ProductExtractRequest = { raw_text: rawText }
      const res = await CommerceTasksService.enqueueProductExtractApiV1CommerceProductsExtractPost({
        requestBody: body,
      })
      if (!res.data) throw new Error('empty enqueue response')
      return res.data
    },
  })
}
