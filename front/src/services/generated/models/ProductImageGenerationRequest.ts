/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 触发商品参考图生成的请求体。
 *
 * 字段说明：
 * view_angle:
 * 视角，沿用 :class:`AssetViewAngle` 枚举值（``FRONT`` /
 * ``LEFT`` / ``RIGHT`` / ``BACK`` / ``THREE_QUARTER`` /
 * ``TOP`` / ``DETAIL``）。``FRONT`` 命中 ``product_image_front_v1``
 * 模板，其余角度命中 ``product_image_other_v1`` 模板。
 * quality_level:
 * 质量等级（``LOW`` / ``MEDIUM`` / ``HIGH`` / ``ULTRA``）。
 * 会被原样写入 ``run_args`` 供下游 worker 决定模型档位与采样
 * 参数；不影响模板选择。
 * reference_file_id:
 * 可选参考图。若传入，会以 ``[{"id": ..., "kind": "reference"}]``
 * 形式塞进 ``run_args.input.images``，作为图生图基底；为空表示
 * 纯文生图。
 */
export type ProductImageGenerationRequest = {
    view_angle?: string;
    quality_level?: string;
    reference_file_id?: (string | null);
};

