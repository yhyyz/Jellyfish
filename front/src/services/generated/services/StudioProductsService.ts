/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_dict_str__Any__ } from '../models/ApiResponse_dict_str__Any__';
import type { ApiResponse_PaginatedData_dict_str__Any___ } from '../models/ApiResponse_PaginatedData_dict_str__Any___';
import type { ApiResponse_ProductImageGenerationResponse_ } from '../models/ApiResponse_ProductImageGenerationResponse_';
import type { ProductCreate } from '../models/ProductCreate';
import type { ProductImageCreate } from '../models/ProductImageCreate';
import type { ProductImageGenerationRequest } from '../models/ProductImageGenerationRequest';
import type { ProductUpdate } from '../models/ProductUpdate';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class StudioProductsService {
    /**
     * 商品列表（分页）
     * 商品分页列表：q 为关键字，category/style/visual_style 为枚举值过滤。
     * @returns ApiResponse_PaginatedData_dict_str__Any___ Successful Response
     * @throws ApiError
     */
    public static listProductsApiV1StudioProductsGet({
        q,
        category,
        style,
        visualStyle,
        order,
        isDesc = false,
        page = 1,
        pageSize = 10,
    }: {
        /**
         * 按名称/描述模糊搜索
         */
        q?: (string | null),
        /**
         * 按 ProductCategory 过滤
         */
        category?: (string | null),
        /**
         * 按 ProjectStyle 过滤
         */
        style?: (string | null),
        /**
         * 按 ProjectVisualStyle 过滤
         */
        visualStyle?: (string | null),
        /**
         * 排序字段：name/created_at/updated_at
         */
        order?: (string | null),
        /**
         * 是否倒序
         */
        isDesc?: boolean,
        page?: number,
        pageSize?: number,
    }): CancelablePromise<ApiResponse_PaginatedData_dict_str__Any___> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/products',
            query: {
                'q': q,
                'category': category,
                'style': style,
                'visual_style': visualStyle,
                'order': order,
                'is_desc': isDesc,
                'page': page,
                'page_size': pageSize,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 创建商品
     * 创建商品；id 缺省由 service 层生成 uuid4().hex。
     * @returns ApiResponse_dict_str__Any__ Successful Response
     * @throws ApiError
     */
    public static createProductApiV1StudioProductsPost({
        requestBody,
    }: {
        requestBody: ProductCreate,
    }): CancelablePromise<ApiResponse_dict_str__Any__> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/products',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 商品详情（含图片）
     * 商品详情，附带 images 子集合（按 image.id 升序）。
     * @returns ApiResponse_dict_str__Any__ Successful Response
     * @throws ApiError
     */
    public static getProductApiV1StudioProductsProductIdGet({
        productId,
    }: {
        productId: string,
    }): CancelablePromise<ApiResponse_dict_str__Any__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/products/{product_id}',
            path: {
                'product_id': productId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 更新商品
     * 部分更新；仅写入请求中显式提供的字段。
     * @returns ApiResponse_dict_str__Any__ Successful Response
     * @throws ApiError
     */
    public static updateProductApiV1StudioProductsProductIdPatch({
        productId,
        requestBody,
    }: {
        productId: string,
        requestBody: ProductUpdate,
    }): CancelablePromise<ApiResponse_dict_str__Any__> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/studio/products/{product_id}',
            path: {
                'product_id': productId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 删除商品（级联删除关联图片和项目链接）
     * 删除商品：DB 级 CASCADE 会清理 product_images 与 project_product_links。
     * @returns void
     * @throws ApiError
     */
    public static deleteProductApiV1StudioProductsProductIdDelete({
        productId,
    }: {
        productId: string,
    }): CancelablePromise<void> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/studio/products/{product_id}',
            path: {
                'product_id': productId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 添加商品图
     * 挂载商品图：(product_id, quality_level, view_angle) 唯一，冲突 → 409。
     * @returns ApiResponse_dict_str__Any__ Successful Response
     * @throws ApiError
     */
    public static addProductImageApiV1StudioProductsProductIdImagesPost({
        productId,
        requestBody,
    }: {
        productId: string,
        requestBody: ProductImageCreate,
    }): CancelablePromise<ApiResponse_dict_str__Any__> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/products/{product_id}/images',
            path: {
                'product_id': productId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 删除商品图
     * 删除指定商品下的图片；image 不属于该 product 时返回 404。
     * @returns void
     * @throws ApiError
     */
    public static deleteProductImageApiV1StudioProductsProductIdImagesImageIdDelete({
        productId,
        imageId,
    }: {
        productId: string,
        imageId: number,
    }): CancelablePromise<void> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/studio/products/{product_id}/images/{image_id}',
            path: {
                'product_id': productId,
                'image_id': imageId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 生成商品参考图（异步任务）
     * 触发 image_generation 任务，结果完成后由下游 worker 自动写 ProductImage 行。
     *
     * 路由职责（保持瘦身）：
     * 1. 自动校验入参（``ProductImageGenerationRequest`` 已声明 extra="forbid"）；
     * 2. 调用 :class:`ProductImageGenerationService` 完成模板解析 / 渲染 / 入队；
     * 3. 把 service 返回的 dict 包成 :class:`ProductImageGenerationResponse`，
     * 再走统一响应壳 ``ApiResponse``，状态码固定 ``202 Accepted``（语义
     * 与 W6-T3 ``commerce*`` 任务入口一致：请求已接收、处理尚未完成）。
     * @returns ApiResponse_ProductImageGenerationResponse_ Successful Response
     * @throws ApiError
     */
    public static generateProductImageApiV1StudioProductsProductIdImagesGeneratePost({
        productId,
        requestBody,
    }: {
        productId: string,
        requestBody: ProductImageGenerationRequest,
    }): CancelablePromise<ApiResponse_ProductImageGenerationResponse_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/products/{product_id}/images/generate',
            path: {
                'product_id': productId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
