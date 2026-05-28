/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_Token_ } from '../models/ApiResponse_Token_';
import type { Body_login_access_token_api_v1_login_access_token_post } from '../models/Body_login_access_token_api_v1_login_access_token_post';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class AuthService {
    /**
     * 登录获取 JWT access token（OAuth2 password flow）
     * 以 username + password 登录，颁发 HS256 编码的 JWT access token。
     *
     * - 输入：OAuth2 标准 form data（``username`` + ``password``）。
     * - 输出：``ApiResponse[Token]``，含 ``access_token`` / ``token_type=bearer`` /
     * ``expires_in`` 三字段。
     *
     * Raises:
     * HTTPException 401: 用户不存在或密码错误（统一消息）。
     * HTTPException 400: 用户存在但 ``is_active=False``。
     * @returns ApiResponse_Token_ Successful Response
     * @throws ApiError
     */
    public static loginAccessTokenApiV1LoginAccessTokenPost({
        formData,
    }: {
        formData: Body_login_access_token_api_v1_login_access_token_post,
    }): CancelablePromise<ApiResponse_Token_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/login/access-token',
            formData: formData,
            mediaType: 'application/x-www-form-urlencoded',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
