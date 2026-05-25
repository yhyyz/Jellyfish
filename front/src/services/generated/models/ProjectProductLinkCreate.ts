/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ProductAppearanceTiming } from './ProductAppearanceTiming';
import type { ProductRoleInStory } from './ProductRoleInStory';
/**
 * 商品关联创建请求体。
 *
 * 路径参数已经携带 ``project_id`` 与 ``product_id``，因此 body 只承载
 * 剧情节奏控制字段；``chapter_id``/``shot_id`` 在 P1 留空（项目级
 * 挂载），后续阶段如需更细粒度可在 body 内扩展。
 */
export type ProjectProductLinkCreate = {
    /**
     * 商品在剧情中的角色
     */
    role_in_story?: ProductRoleInStory;
    /**
     * 出现时机
     */
    appearance_timing?: ProductAppearanceTiming;
    /**
     * 出现时长（秒）
     */
    appearance_duration_sec?: number;
};

