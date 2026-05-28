/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 以 ``api_key_hash`` 为唯一键的 POST body。
 *
 * ``revoke`` / ``usage`` 接口共用，避免在 URL path 中携带 bcrypt
 * hash（含 ``$``、``/`` 等不友好字符）。
 */
export type ApiKeyHashRequest = {
    /**
     * 目标 key 的 bcrypt hash，由 create 响应一次性返回，可在 list 接口再次获取
     */
    api_key_hash: string;
};

