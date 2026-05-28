/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { UserRole } from './UserRole';
/**
 * admin 更新用户的请求体（所有字段可选；password 单独走也走此入口）。
 */
export type UserUpdate = {
    email?: (string | null);
    password?: (string | null);
    role?: (UserRole | null);
    is_active?: (boolean | null);
};

