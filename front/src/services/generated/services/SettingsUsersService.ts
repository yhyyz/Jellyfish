/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_NoneType_ } from '../models/ApiResponse_NoneType_';
import type { ApiResponse_PaginatedData_UserRead__ } from '../models/ApiResponse_PaginatedData_UserRead__';
import type { ApiResponse_UserRead_ } from '../models/ApiResponse_UserRead_';
import type { UserCreate } from '../models/UserCreate';
import type { UserRole } from '../models/UserRole';
import type { UserUpdate } from '../models/UserUpdate';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class SettingsUsersService {
    /**
     * 列出用户（分页 + role / is_active 过滤）
     * admin 列表查询，默认按 ``created_at DESC`` 排序。
     * @returns ApiResponse_PaginatedData_UserRead__ Successful Response
     * @throws ApiError
     */
    public static listUsersEndpointApiV1SettingsUsersGet({
        role,
        isActive,
        page = 1,
        pageSize = 20,
        authorization,
    }: {
        role?: (UserRole | null),
        isActive?: (boolean | null),
        page?: number,
        pageSize?: number,
        authorization?: (string | null),
    }): CancelablePromise<ApiResponse_PaginatedData_UserRead__> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/settings/users',
            headers: {
                'authorization': authorization,
            },
            query: {
                'role': role,
                'is_active': isActive,
                'page': page,
                'page_size': pageSize,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 创建用户
     * admin 创建一条新用户行。username / email 已存在 → 409。
     * @returns ApiResponse_UserRead_ Successful Response
     * @throws ApiError
     */
    public static createUserEndpointApiV1SettingsUsersPost({
        requestBody,
        authorization,
    }: {
        requestBody: UserCreate,
        authorization?: (string | null),
    }): CancelablePromise<ApiResponse_UserRead_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/settings/users',
            headers: {
                'authorization': authorization,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 更新用户（email / role / is_active / password 可选）
     * admin 更新指定 user 的可变字段。
     * @returns ApiResponse_UserRead_ Successful Response
     * @throws ApiError
     */
    public static updateUserEndpointApiV1SettingsUsersUserIdPatch({
        userId,
        requestBody,
        authorization,
    }: {
        userId: string,
        requestBody: UserUpdate,
        authorization?: (string | null),
    }): CancelablePromise<ApiResponse_UserRead_> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/settings/users/{user_id}',
            path: {
                'user_id': userId,
            },
            headers: {
                'authorization': authorization,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * 软删除用户（is_active=False）
     * admin 软删除指定 user；admin 不允许删除自己。
     * @returns ApiResponse_NoneType_ Successful Response
     * @throws ApiError
     */
    public static softDeleteUserEndpointApiV1SettingsUsersUserIdDelete({
        userId,
        authorization,
    }: {
        userId: string,
        authorization?: (string | null),
    }): CancelablePromise<ApiResponse_NoneType_> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/settings/users/{user_id}',
            path: {
                'user_id': userId,
            },
            headers: {
                'authorization': authorization,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
