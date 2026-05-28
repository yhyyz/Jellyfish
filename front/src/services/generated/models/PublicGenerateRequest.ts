/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * ``POST /api/v1/public/commerce/generate`` 的请求体。
 *
 * Attributes:
 * product_id: 目标商品主键；必须先在 admin 通道入库，否则 endpoint
 * 返回 404（而非静默 placeholder），强制调用方按规范注册商品。
 * formula_id: :class:`app.models.story_formula.StoryFormula` 主键；
 * 未注册的 ``formula_id`` 同样返回 404。
 * archetype: 可选品牌人格原型字符串；为空时由 worker 取项目默认。
 * schema 层不约束取值范围，下游 worker 会按 brand_archetypes
 * 注册表做降级处理。
 * platform_preset_id: 可选 :class:`PlatformExportPreset` 主键，用于
 * 约定输出画幅 / 时长 / 字幕样式；不传时 worker 走章节级默认。
 * variant_count: 一次调用产出的变体数；P4 P0 钳制在 1-6 区间，避免
 * 单租户阻塞批量队列。
 *
 * 设计注释：
 *
 * - ``model_config = ConfigDict(extra="forbid")`` 与既有 commerce
 * 请求体一致，避免老调用方误传字段被静默吞掉，对外契约无歧义；
 * - 字段全部使用 ``Field(...)`` 的显式约束（``min_length``、``ge``、
 * ``le``）以便 FastAPI 自动产出 422 + 详细 JSON Schema，第三方调
 * 用方不需要看后端代码就能知道每个字段的取值范围。
 */
export type PublicGenerateRequest = {
    /**
     * 目标商品主键（必须先在 admin 通道入库；不存在 → 404）
     */
    product_id: string;
    /**
     * 剧情公式 ID（如 underdog_triumph；不存在 → 404）
     */
    formula_id: string;
    /**
     * 可选品牌人格原型；为空时由 worker 取项目默认值
     */
    archetype?: (string | null);
    /**
     * 可选 PlatformExportPreset ID；不传时走章节级默认
     */
    platform_preset_id?: (string | null);
    /**
     * 一次调用希望产出的变体数；钳制在 1-6 区间（P4 P0 SLA）
     */
    variant_count?: number;
};

