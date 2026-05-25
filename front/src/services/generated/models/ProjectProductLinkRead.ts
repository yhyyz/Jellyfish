/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ProductAppearanceTiming } from './ProductAppearanceTiming';
import type { ProductRoleInStory } from './ProductRoleInStory';
/**
 * 商品关联只读视图。
 */
export type ProjectProductLinkRead = {
    /**
     * 自增主键
     */
    id: number;
    /**
     * 项目 ID
     */
    project_id: string;
    /**
     * 章节 ID（P1 留空）
     */
    chapter_id?: (string | null);
    /**
     * 镜头 ID（P1 留空）
     */
    shot_id?: (string | null);
    /**
     * 商品 ID
     */
    product_id: string;
    /**
     * 角色
     */
    role_in_story: ProductRoleInStory;
    /**
     * 时机
     */
    appearance_timing: ProductAppearanceTiming;
    /**
     * 时长（秒）
     */
    appearance_duration_sec: number;
};

