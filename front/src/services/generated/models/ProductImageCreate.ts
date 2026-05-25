/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AssetQualityLevel } from './AssetQualityLevel';
import type { AssetViewAngle } from './AssetViewAngle';
/**
 * 上传/挂载商品图请求体。
 *
 * 在 (product_id, quality_level, view_angle) 维度上唯一（参见
 * ``ProductImage.uq_product_images_quality_angle``），重复时 service 层
 * 捕获 ``IntegrityError`` 并转 409。
 */
export type ProductImageCreate = {
    file_id: string;
    quality_level?: AssetQualityLevel;
    view_angle?: AssetViewAngle;
    is_primary?: boolean;
    width?: (number | null);
    height?: (number | null);
    fmt?: (string | null);
};

