/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { UserRole } from './UserRole';
/**
 * admin 创建用户的请求体。
 */
export type UserCreate = {
    username: string;
    email: string;
    password: string;
    role?: UserRole;
    is_active?: boolean;
};

