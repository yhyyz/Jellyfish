/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_UserRead_ } from '../models/ApiResponse_UserRead_';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class UsersService {
    /**
     * 查询当前登录用户 profile
     * 返回当前 JWT（或 Stage-1 静态 fallback）关联的 :class:`User`。
     *
     * 任何已登录用户都可调用（不限制 role），前端 ``AuthContext`` 用此
     * 端点在登录后立即拉真实 role，避免硬编码导致 member 看到 admin 入口。
     *
     * Stage-1 静态 fallback 行为：
     * ``settings.jwt_fallback_to_static=True`` 且 ``Authorization``
     * 头为 ``Bearer <settings.api_key>`` 时，返回内存虚拟 admin
     * （``id=__static_fallback__``，``role=ADMIN``，``is_active=True``）。
     * 这是有意义的 —— 前端通过 fallback 登录时也能拿到 ``role=admin``。
     *
     * Returns:
     * :class:`ApiResponse[UserRead]`: 当前用户的 ``id`` / ``username``
     * / ``email`` / ``role`` / ``is_active`` / ``created_at`` /
     * ``updated_at``。响应不会暴露 ``hashed_password``。
     * @returns ApiResponse_UserRead_ Successful Response
     * @throws ApiError
     */
    public static readUsersMeApiV1UsersMeGet({
        authorization,
    }: {
        authorization?: (string | null),
    }): CancelablePromise<ApiResponse_UserRead_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/users/me',
            headers: {
                'authorization': authorization,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
