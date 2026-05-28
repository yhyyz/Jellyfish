/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { UserRole } from './UserRole';
/**
 * 用户信息读响应（不包含 hashed_password）。
 */
export type UserRead = {
    /**
     * UUID hex string
     */
    id: string;
    username: string;
    email: string;
    role: UserRole;
    is_active: boolean;
    created_at: string;
    updated_at: string;
};

