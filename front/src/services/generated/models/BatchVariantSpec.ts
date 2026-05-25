/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 批量生成中单个变体的参数规格（参数网格里的一行）。
 *
 * 存在原因：
 * ``story_video_batch_generate`` 任务一次性入队 N 个
 * ``story_script_generate`` 子任务做参数网格扫描，每行需要描述
 * “要换哪些公式 / 原型 / 钩子 / CTA / 调性网格”。把这一行抽成
 * 独立模型而不是 dict[str, Any]，可以让前端在联调期就能拿到
 * 422 的明确反馈，避免拼写错误漂到 worker 层才报错。
 *
 * Attributes:
 * formula_id: 该变体使用的故事公式 ID（必填）。
 * archetype: 该变体的品牌人格原型；为空时使用项目默认值。
 * hook_pattern_id: 钩子模式 ID；为空表示沿用公式默认开场。
 * cta_pattern_id: CTA 模式 ID；为空表示沿用公式默认结尾。
 * tone_grid: 调性网格 dimension -> 0~10 整数刻度；缺省为空 dict。
 * label: 用户备注（如 "v1-hero" / "v2-control"），用于在结果面板
 * 上一眼区分批量结果。
 */
export type BatchVariantSpec = {
    /**
     * 该变体使用的故事公式 ID
     */
    formula_id: string;
    /**
     * 品牌人格原型；为空时使用项目/批量级默认值
     */
    archetype?: (string | null);
    /**
     * 钩子模式 ID；为空表示沿用公式默认开场
     */
    hook_pattern_id?: (string | null);
    /**
     * CTA 模式 ID；为空表示沿用公式默认结尾
     */
    cta_pattern_id?: (string | null);
    /**
     * 调性网格：dimension -> 0~10 整数刻度
     */
    tone_grid?: Record<string, number>;
    /**
     * 用户备注，例如 v1-hero / v2-control，便于结果对照
     */
    label?: (string | null);
};

