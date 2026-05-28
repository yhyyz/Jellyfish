/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 品牌话术规范响应模型（与 ORM 字段一一对应）。
 */
export type BrandStyleGuideRead = {
    id: string;
    product_id: string;
    forced_phrases: Array<string>;
    banned_patterns: Array<string>;
    required_endings: Array<string>;
    brand_persona_tagline: string;
    created_at: string;
    updated_at: string;
};

