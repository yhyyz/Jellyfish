/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { RowError } from './RowError';
/**
 * 批量导入的整体汇总。
 *
 * HTTP 200 + summary 即视为一次成功的批处理；失败行不会让整批 abort，
 * 由 ``errors`` 字段单独展示。前端可基于 ``inserted`` / ``failed``
 * 决定是否提示成功，并通过 ``errors`` 表格让用户修正错误后重传。
 */
export type ImportSummary = {
    /**
     * 总数据行（不含 header）
     */
    total_rows: number;
    /**
     * 成功写入条数
     */
    inserted: number;
    /**
     * 失败行数 = len(errors)
     */
    failed: number;
    /**
     * 使用的 mapping profile 名
     */
    mapping_profile: string;
    /**
     * 逐行失败明细（按 row_index 升序）
     */
    errors?: Array<RowError>;
};

