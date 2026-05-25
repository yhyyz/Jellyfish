/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * BrandArchetype 只读响应。
 *
 * 用于 ``GET /api/v1/studio/brand-archetypes`` 列表与详情。
 * ``voice_traits`` / ``speech_patterns`` / ``sample_brands`` 三个 JSON
 * 列保留原始结构，前端原型卡片可直接渲染 do/dont 与代表品牌。
 *
 * 注：``voice_traits`` 在 ORM 中以 ``list[str]`` 存储，但本响应将其暴
 * 露为 ``dict[str, Any]`` 以兼容上游期望（见 W14-T4 OUTCOME 规约）。
 * 实际由 :class:`app.services.commerce.pattern_library.PatternLibraryService`
 * 在序列化时按需包裹，避免 schema 与 ORM 列形状强耦合。
 */
export type BrandArchetypeRead = {
    /**
     * 原型 ID（如 sage / jester）
     */
    id: string;
    /**
     * 英文名称（Sage / Jester / ...）
     */
    name: string;
    /**
     * 中文名称（智者 / 小丑 / ...）
     */
    name_zh: string;
    /**
     * 核心动机（80-150 字）
     */
    motivation: string;
    /**
     * 语调描述符，结构 {items: [...]}
     */
    voice_traits?: Record<string, any>;
    /**
     * 语言模式 JSON：{do: [...], dont: [...]}
     */
    speech_patterns?: Record<string, any>;
    /**
     * 代表品牌列表
     */
    sample_brands?: Array<string>;
    /**
     * 系统原型标记
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

