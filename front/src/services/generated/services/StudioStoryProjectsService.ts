/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_list_StoryProjectRead__ } from '../models/ApiResponse_list_StoryProjectRead__';
import type { ApiResponse_NoneType_ } from '../models/ApiResponse_NoneType_';
import type { ApiResponse_ProjectProductLinkRead_ } from '../models/ApiResponse_ProjectProductLinkRead_';
import type { ApiResponse_StoryProjectRead_ } from '../models/ApiResponse_StoryProjectRead_';
import type { ProjectProductLinkCreate } from '../models/ProjectProductLinkCreate';
import type { StoryProjectConfigUpdate } from '../models/StoryProjectConfigUpdate';
import type { StoryProjectCreate } from '../models/StoryProjectCreate';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class StudioStoryProjectsService {
    /**
     * 剧情带货项目列表（仅 kind=commerce_story）
     * 返回所有 commerce_story 项目，附带 1:1 配置。
     * @returns ApiResponse_list_StoryProjectRead__ Successful Response
     * @throws ApiError
     */
    public static listStoryProjectsApiV1StudioStoryProjectsGet(): CancelablePromise<ApiResponse_list_StoryProjectRead__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/story-projects',
        });
    }
    /**
     * 创建剧情带货项目（Project + CommerceStoryConfig 单事务）
     * 同事务创建 Project（kind=commerce_story 强制）+ CommerceStoryConfig。
     * @returns ApiResponse_StoryProjectRead_ Successful Response
     * @throws ApiError
     */
    public static createStoryProjectApiV1StudioStoryProjectsPost({
        requestBody,
    }: {
        requestBody: StoryProjectCreate,
    }): CancelablePromise<ApiResponse_StoryProjectRead_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/story-projects',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 剧情带货项目详情
     * 读取项目详情（含 1:1 CommerceStoryConfig）。
     * @returns ApiResponse_StoryProjectRead_ Successful Response
     * @throws ApiError
     */
    public static getStoryProjectApiV1StudioStoryProjectsProjectIdGet({
        projectId,
    }: {
        projectId: string,
    }): CancelablePromise<ApiResponse_StoryProjectRead_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/studio/story-projects/{project_id}',
            path: {
                'project_id': projectId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 更新剧情带货项目配置（仅 CommerceStoryConfig 字段）
     * patch CommerceStoryConfig；不动 Project 核心字段。
     * @returns ApiResponse_StoryProjectRead_ Successful Response
     * @throws ApiError
     */
    public static updateStoryProjectConfigApiV1StudioStoryProjectsProjectIdConfigPatch({
        projectId,
        requestBody,
    }: {
        projectId: string,
        requestBody: StoryProjectConfigUpdate,
    }): CancelablePromise<ApiResponse_StoryProjectRead_> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/studio/story-projects/{project_id}/config',
            path: {
                'project_id': projectId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 为剧情带货项目挂载商品
     * 在 ``project_product_links`` 上 INSERT 一条项目级挂载。
     * @returns ApiResponse_ProjectProductLinkRead_ Successful Response
     * @throws ApiError
     */
    public static linkStoryProjectProductApiV1StudioStoryProjectsProjectIdProductsProductIdPost({
        projectId,
        productId,
        requestBody,
    }: {
        projectId: string,
        productId: string,
        requestBody: ProjectProductLinkCreate,
    }): CancelablePromise<ApiResponse_ProjectProductLinkRead_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/studio/story-projects/{project_id}/products/{product_id}',
            path: {
                'project_id': projectId,
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
     * 取消剧情带货项目的商品挂载
     * 从 ``project_product_links`` 上删除 (project_id, product_id) 项目级挂载。
     * @returns ApiResponse_NoneType_ Successful Response
     * @throws ApiError
     */
    public static unlinkStoryProjectProductApiV1StudioStoryProjectsProjectIdProductsProductIdDelete({
        projectId,
        productId,
    }: {
        projectId: string,
        productId: string,
    }): CancelablePromise<ApiResponse_NoneType_> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/studio/story-projects/{project_id}/products/{product_id}',
            path: {
                'project_id': projectId,
                'product_id': productId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
