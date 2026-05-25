/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { StoryVariantStatus } from './StoryVariantStatus';
/**
 * StoryVariant 只读响应。
 *
 * 暴露 P1 业务关心的全部字段；P2 预留字段（``hook_pattern_id`` /
 * ``cta_pattern_id`` / ``is_champion``）作为只读返回，前端可在 P2
 * UI 下分阶段启用。
 */
export type StoryVariantRead = {
    /**
     * 变体唯一 ID
     */
    id: string;
    /**
     * 所属项目
     */
    project_id: string;
    /**
     * 所属章节
     */
    chapter_id: string;
    /**
     * 使用的剧情公式 ID
     */
    formula_id: string;
    /**
     * 钩子模式 ID（P2）
     */
    hook_pattern_id?: (string | null);
    /**
     * CTA 模式 ID（P2）
     */
    cta_pattern_id?: (string | null);
    /**
     * 品牌人格
     */
    archetype?: (string | null);
    /**
     * 完整剧本文本
     */
    script_full_text: string;
    /**
     * 镜头分解结果 JSON
     */
    script_breakdown?: Record<string, any>;
    /**
     * 状态
     */
    status: StoryVariantStatus;
    /**
     * 是否冠军变体（P2）
     */
    is_champion: boolean;
    /**
     * 合规评分 0-100
     */
    compliance_score: number;
    /**
     * 生成此变体的 GenerationTask ID
     */
    generated_by_task_id?: (string | null);
    /**
     * 创建时间
     */
    created_at?: (string | null);
    /**
     * 最近更新时间
     */
    updated_at?: (string | null);
};

