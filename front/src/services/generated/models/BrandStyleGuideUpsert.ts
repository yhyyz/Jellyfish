/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 创建 / 替换 / 部分更新品牌话术规范的请求体。
 *
 * 所有字段均可选 + 有默认值，便于前端在内容尚未补齐时也能保存一份草稿。
 * PATCH 场景使用 ``model_dump(exclude_unset=True)`` 仅取显式提供字段，
 * POST upsert 场景使用 ``model_dump()`` 取完整对象，未传字段回落到默认。
 */
export type BrandStyleGuideUpsert = {
    forced_phrases?: (Array<string> | null);
    banned_patterns?: (Array<string> | null);
    required_endings?: (Array<string> | null);
    brand_persona_tagline?: (string | null);
};

