/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * ``POST /api/v1/commerce/script-generate`` 请求体。
 *
 * 剧情脚本生成的输入比商品抽取复杂：除了项目/章节锚点外，还包含商品快照、
 * 受众画像、原型、调性栅格、目标时长、投放平台等参数。这些字段不再走
 * ``extra=allow``，目的是在前后端联调期就能识别出过期 / 拼写错误的字段。
 *
 * Attributes:
 * project_id: 所属项目 ID。
 * chapter_id: 所属章节 ID（剧情带货项目仍按章节组织剧本）。
 * formula_id: 选用的故事公式 ID（来自 ``story_formulas``）。
 * product: 商品快照 JSON（worker 在执行时不再回查 DB，确保历史可追溯）。
 * audience: 受众画像 JSON（年龄层 / 性别 / 兴趣标签等）。
 * archetype: 角色原型，默认 ``Sage``，与 ``StoryScriptGeneratorAgent`` 对齐。
 * tone_grid: 调性栅格（认真/幽默、专业/接地气等坐标）。
 * target_duration_sec: 目标视频时长（秒），15 ≤ x ≤ 180。
 * platform: 目标投放平台，默认 ``douyin``，由 worker 决定地域/口径。
 */
export type ScriptGenerateRequest = {
    /**
     * 所属项目 ID
     */
    project_id: string;
    /**
     * 所属章节 ID
     */
    chapter_id: string;
    /**
     * 使用的故事公式 ID
     */
    formula_id: string;
    /**
     * 商品快照 JSON
     */
    product: Record<string, any>;
    /**
     * 受众画像 JSON
     */
    audience: Record<string, any>;
    /**
     * 叙事原型，默认 Sage
     */
    archetype?: string;
    /**
     * 调性栅格 JSON
     */
    tone_grid?: Record<string, any>;
    /**
     * 目标视频时长（秒），约束在 15–180 之间
     */
    target_duration_sec: number;
    /**
     * 目标投放平台，默认 douyin
     */
    platform?: string;
};

