/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ComplianceRegion } from './ComplianceRegion';
import type { Platform } from './Platform';
/**
 * CommerceStoryConfig 只读视图（嵌入 StoryProjectRead）。
 */
export type CommerceStoryConfigRead = {
    /**
     * 目标平台
     */
    target_platform?: Platform;
    /**
     * 目标时长（秒）
     */
    target_duration_sec?: number;
    /**
     * 选定的剧情公式 ID（StoryFormula.id）
     */
    formula_id?: (string | null);
    /**
     * 品牌人格 archetype（P2 启用 BrandArchetype 枚举）
     */
    archetype?: (string | null);
    /**
     * 语调维度 JSON
     */
    tone_grid?: Record<string, any>;
    /**
     * 覆盖商品默认受众的项目级配置
     */
    audience_override?: (Record<string, any> | null);
    /**
     * 合规地域
     */
    compliance_region?: ComplianceRegion;
    /**
     * 合规规则集 ID
     */
    compliance_profile_id?: string;
    /**
     * 目标 KPI: awareness/clicks/conversion
     */
    target_kpi?: (string | null);
    /**
     * 所属项目 ID
     */
    project_id: string;
};

