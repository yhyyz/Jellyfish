/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 手动创建 StoryVariant 的请求体。
 *
 * ``id`` 由服务层生成（``uuid4().hex``），不接受客户端传入。
 * ``status`` / ``is_champion`` / ``compliance_score`` 同样由服务端固
 * 定，避免客户端绕过 A/B 评估机制提前置位。
 */
export type StoryVariantCreate = {
    /**
     * 所属项目 ID
     */
    project_id: string;
    /**
     * 所属章节 ID
     */
    chapter_id: string;
    /**
     * 使用的剧情公式 ID
     */
    formula_id: string;
    /**
     * 完整剧本文本
     */
    script_full_text: string;
    /**
     * 镜头分解结果 JSON
     */
    script_breakdown?: Record<string, any>;
    /**
     * 品牌人格 archetype（P2 启用 BrandArchetype 枚举）
     */
    archetype?: (string | null);
    /**
     * 生成此变体的 GenerationTask ID（无硬 FK）
     */
    generated_by_task_id?: (string | null);
};

