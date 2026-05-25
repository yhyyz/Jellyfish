/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ProductCategory } from './ProductCategory';
import type { ProjectStyle } from './ProjectStyle';
import type { ProjectVisualStyle } from './ProjectVisualStyle';
/**
 * 创建商品请求体。
 *
 * `id` 不传则由 service 层使用 ``uuid4().hex`` 自动生成；`name` 在全库范围
 * 唯一（参见 ``Product.uq_products_name``），冲突由 service 层捕获
 * ``IntegrityError`` 并转换为 409。
 */
export type ProductCreate = {
    id?: (string | null);
    name: string;
    brand?: string;
    category?: ProductCategory;
    description?: string;
    price_anchor?: (number | null);
    sku?: (string | null);
    selling_points?: Array<string>;
    pain_points_solved?: Array<string>;
    target_audience?: Record<string, any>;
    catchphrases?: Array<string>;
    competitor_names?: Array<string>;
    health_disclaimer_required?: boolean;
    visual_style?: ProjectVisualStyle;
    style: ProjectStyle;
    prompt_template_id?: (string | null);
};

