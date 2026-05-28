/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ConsistencyEvidenceRead } from './ConsistencyEvidenceRead';
export type ApiResponse_ConsistencyEvidenceRead_ = {
    /**
     * 与 HTTP 状态码一致
     */
    code?: number;
    /**
     * 提示信息
     */
    message?: string;
    /**
     * 实际数据
     */
    data?: (ConsistencyEvidenceRead | null);
    /**
     * 附加元信息
     */
    meta?: (Record<string, any> | null);
};

