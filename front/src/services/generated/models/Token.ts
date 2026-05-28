/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 登录成功后的 access token 响应载荷。
 *
 * 序列化遵循 OAuth2 password flow 习惯：
 * - ``access_token``：JWT 字符串本体；
 * - ``token_type``：固定为 ``"bearer"``；
 * - ``expires_in``：剩余有效秒数（前端可用作自动登出倒计时）。
 */
export type Token = {
    /**
     * JWT access token (HS256)
     */
    access_token: string;
    /**
     * Token 类型，固定为 bearer
     */
    token_type?: string;
    /**
     * 剩余有效秒数（与 ACCESS_TOKEN_EXPIRE_MINUTES 一致）
     */
    expires_in: number;
};

