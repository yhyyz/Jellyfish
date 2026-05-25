/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ProductCategory } from './ProductCategory';
import type { ProjectStyle } from './ProjectStyle';
import type { ProjectVisualStyle } from './ProjectVisualStyle';
/**
 * 部分更新商品（PATCH）—— 全字段可选。
 *
 * 通过 ``model_dump(exclude_unset=True)`` 可只取请求中显式提供的字段，
 * 避免把 None 误覆盖到既有非空字段上。
 */
export type ProductUpdate = {
    name?: (string | null);
    brand?: (string | null);
    category?: (ProductCategory | null);
    description?: (string | null);
    price_anchor?: (number | null);
    sku?: (string | null);
    selling_points?: (Array<string> | null);
    pain_points_solved?: (Array<string> | null);
    target_audience?: (Record<string, any> | null);
    catchphrases?: (Array<string> | null);
    competitor_names?: (Array<string> | null);
    health_disclaimer_required?: (boolean | null);
    visual_style?: (ProjectVisualStyle | null);
    style?: (ProjectStyle | null);
    prompt_template_id?: (string | null);
};

