/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 商品参考图生成入队响应。
 *
 * 字段说明：
 * task_id:
 * ``GenerationTask`` 主键（``uuid4().hex`` 形式）；前端可用其
 * 轮询 ``/api/v1/tasks/{task_id}`` 获取进度与结果。
 * product_id:
 * 目标商品 ID，回显方便前端绑定 toast / 任务列表。
 * view_angle:
 * 实际生效的视角值（service 会做规范化）。
 * template_used:
 * 实际命中的提示词模板 ID（如 ``product_image_front_v1`` /
 * ``product_image_other_v1`` / 或 ``product.prompt_template_id``
 * 指向的自定义模板）。便于排障与 A/B 验证。
 */
export type ProductImageGenerationResponse = {
    task_id: string;
    product_id: string;
    view_angle: string;
    template_used: string;
};

