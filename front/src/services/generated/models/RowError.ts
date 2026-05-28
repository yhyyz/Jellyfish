/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * CSV 单行解析或写库失败的描述。
 *
 * 保留 ``raw_row`` 是为了让前端可以"原样回显"问题数据，便于运营同学
 * 比对原 CSV 排查；``reason`` 为简明文案，避免向前端暴露 traceback。
 */
export type RowError = {
    /**
     * CSV 中的行号（1-based，包含 header；header 行号为 1）
     */
    row_index: number;
    /**
     * 该行的原始 dict（按 CSV header 解析后），便于前端展示
     */
    raw_row?: Record<string, any>;
    /**
     * 失败原因（中文文案）
     */
    reason: string;
};

