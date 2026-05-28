/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_BrandStyleGuideRead_ } from '../models/ApiResponse_BrandStyleGuideRead_';
import type { ApiResponse_NoneType_ } from '../models/ApiResponse_NoneType_';
import type { BrandStyleGuideUpsert } from '../models/BrandStyleGuideUpsert';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class StudioBrandStyleGuidesService {
    /**
     * 读取商品的品牌话术规范
     * 读取指定商品的品牌话术规范；商品或规范不存在 → 404。
     * @returns ApiResponse_BrandStyleGuideRead_ Successful Response
     * @throws ApiError
     */
    public static getBrandStyleGuideApiV1StudioProductsProductIdBrandStyleGuideGet({
        productId,
    }: {
        productId: string,
    }): CancelablePromise<ApiResponse_BrandStyleGuideRead_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/products/{product_id}/brand-style-guide',
            path: {
                'product_id': productId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 创建或更新（upsert）商品的品牌话术规范
     * upsert 语义：商品已有规范 → 部分更新；尚无规范 → 创建。
     *
     * HTTP 状态码：新建返回 201，更新返回 200，便于前端区分。FastAPI 在
     * decorator 上无法表达 "条件性 status_code"，因此通过注入 ``Response``
     * 动态设置 ``response.status_code``。
     * @returns ApiResponse_BrandStyleGuideRead_ Successful Response
     * @throws ApiError
     */
    public static upsertBrandStyleGuideApiV1StudioProductsProductIdBrandStyleGuidePost({
        productId,
        requestBody,
    }: {
        productId: string,
        requestBody: BrandStyleGuideUpsert,
    }): CancelablePromise<ApiResponse_BrandStyleGuideRead_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/products/{product_id}/brand-style-guide',
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
     * 部分更新商品的品牌话术规范
     * 部分更新；规范不存在时返回 404（与 POST upsert 区分开）。
     * @returns ApiResponse_BrandStyleGuideRead_ Successful Response
     * @throws ApiError
     */
    public static patchBrandStyleGuideApiV1StudioProductsProductIdBrandStyleGuidePatch({
        productId,
        requestBody,
    }: {
        productId: string,
        requestBody: BrandStyleGuideUpsert,
    }): CancelablePromise<ApiResponse_BrandStyleGuideRead_> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/studio/products/{product_id}/brand-style-guide',
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
     * 删除商品的品牌话术规范
     * 删除商品的品牌话术规范；不存在返回 404。
     *
     * 商品被删除时由 DB 级 ``ON DELETE CASCADE`` 同步清理，本接口仅用于
     * 前端"清空规范"场景。
     * @returns ApiResponse_NoneType_ Successful Response
     * @throws ApiError
     */
    public static deleteBrandStyleGuideApiV1StudioProductsProductIdBrandStyleGuideDelete({
        productId,
    }: {
        productId: string,
    }): CancelablePromise<ApiResponse_NoneType_> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/studio/products/{product_id}/brand-style-guide',
            path: {
                'product_id': productId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
