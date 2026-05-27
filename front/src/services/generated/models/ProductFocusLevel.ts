/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 商品在镜头中的视觉聚焦级别（P3 Decision H）。
 *
 * 决定 r2v multi_ref 模式从挂载 ProductImage 取参考图时的角度优先级序列：
 *
 * - subtle: 商品作为背景出现，不影响构图（THREE_QUARTER → FRONT）。
 * - functional: 商品功能性出现（被使用），DETAIL/THREE_QUARTER 角度优先。
 * - hero: 商品 hero 镜头，FRONT/THREE_QUARTER/DETAIL 优先级序列。
 * - none: 镜头无商品出现（走 t2v 而非 r2v）。
 */
export type ProductFocusLevel = 'subtle' | 'functional' | 'hero' | 'none';
