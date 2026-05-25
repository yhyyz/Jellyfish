/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 单个叙事节拍（beat）只读视图。
 *
 * 与 :class:`app.services.commerce.builtin_story_formulas.Beat` 字段对齐，
 * 用于前端逐条渲染镜头组。
 */
export type StoryFormulaBeatRead = {
    /**
     * 节拍唯一名（snake_case）
     */
    id: string;
    /**
     * 本节拍占用秒数
     */
    duration_sec: number;
    /**
     * 本节拍承担的叙事功能
     */
    function: string;
    /**
     * 建议景别
     */
    shot_type: string;
    /**
     * 建议运镜（None 表示静态）
     */
    recommended_camera_movement?: (string | null);
};

