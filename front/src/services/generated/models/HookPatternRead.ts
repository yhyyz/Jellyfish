/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * HookPattern 只读响应。
 *
 * 用于 ``GET /api/v1/studio/hook-patterns`` 列表与详情。字段直接映射自
 * ORM 列，便于前端钩子选择器直接消费。
 */
export type HookPatternRead = {
    /**
     * 钩子 ID（如 question_hook）
     */
    id: string;
    /**
     * 中文名称（如 问句钩子）
     */
    name: string;
    /**
     * 钩子类型：question / conflict / contrast / ...
     */
    pattern_type: string;
    /**
     * 钩子说明（运营/UI 展示）
     */
    description: string;
    /**
     * Jinja2 模板片段
     */
    template_text: string;
    /**
     * 心理学原理
     */
    psychology: string;
    /**
     * 适用场景列表
     */
    use_cases?: Array<string>;
    /**
     * 禁忌场景列表
     */
    avoid_cases?: Array<string>;
    /**
     * 系统模板标记
     */
    is_system: boolean;
    /**
     * UI 显示排序（升序）
     */
    sort_order: number;
    /**
     * 入库时间
     */
    created_at: string;
};

