/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ComplianceRegion } from './ComplianceRegion';
import type { Platform } from './Platform';
/**
 * 更新 CommerceStoryConfig（不含 Project 核心字段）。
 *
 * 全部字段可选，按 ``model_dump(exclude_unset=True)`` 增量 patch。
 */
export type StoryProjectConfigUpdate = {
    target_platform?: (Platform | null);
    target_duration_sec?: (number | null);
    formula_id?: (string | null);
    archetype?: (string | null);
    tone_grid?: (Record<string, any> | null);
    audience_override?: (Record<string, any> | null);
    compliance_region?: (ComplianceRegion | null);
    compliance_profile_id?: (string | null);
    target_kpi?: (string | null);
};

