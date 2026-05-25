/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * ``ComplianceProfile`` 的只读视图。
 *
 * Attributes:
 * id: profile ID（如 ``cn_mainland_default``），可在配置/代码中引用。
 * name: 显示名称。
 * region: 适用地域字符串（``cn_mainland`` / ``hk_tw`` / ``overseas``）。
 * rules: 规则数组 JSON，结构由 :mod:`app.services.compliance.builtin_rules`
 * 决定；前端按 ``kind`` 字段分支渲染。
 * is_system: 是否系统预置；预置 profile 不允许业务侧删除。
 * description: 用途说明，前端展示在卡片副标题位置。
 * created_at: 创建时间，便于审计。
 */
export type ComplianceProfileRead = {
    /**
     * profile ID（如 cn_mainland_default）
     */
    id: string;
    /**
     * 显示名称
     */
    name: string;
    /**
     * 适用地域：cn_mainland / hk_tw / overseas
     */
    region: string;
    /**
     * 规则数组 JSON
     */
    rules?: Array<Record<string, any>>;
    /**
     * 是否系统预置
     */
    is_system: boolean;
    /**
     * profile 用途说明
     */
    description?: string;
    /**
     * 创建时间
     */
    created_at: string;
};

