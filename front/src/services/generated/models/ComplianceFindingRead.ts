/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * ``ComplianceFinding`` 的只读视图。
 *
 * Attributes:
 * id: 自增主键。
 * variant_id: 所属变体 ID（``story_variants.id`` 外键）。
 * severity: 严重度字符串（``info`` / ``warning`` / ``blocker``）。
 * rule_id: 触发的规则 ID。
 * rule_kind: 规则类型（``banned_phrase`` / ``required_label`` / 等）。
 * description: 问题描述。
 * location: 命中位置（如 ``"Shot 3, dialog line 2"``），可能为空。
 * suggested_fix: 建议修复方案，可能为空。
 * is_resolved: 是否已解决；前端默认筛掉已解决项。
 * detected_at: 检测时间。
 */
export type ComplianceFindingRead = {
    /**
     * 自增主键
     */
    id: number;
    /**
     * 所属变体 ID
     */
    variant_id: string;
    /**
     * 严重度：info / warning / blocker
     */
    severity: string;
    /**
     * 触发的规则 ID
     */
    rule_id: string;
    /**
     * 规则类型：banned_phrase / required_label / ...
     */
    rule_kind: string;
    /**
     * 问题描述
     */
    description: string;
    /**
     * 命中位置（如 'Shot 3, dialog line 2'）
     */
    location?: (string | null);
    /**
     * 建议修复方案
     */
    suggested_fix?: (string | null);
    /**
     * 是否已解决
     */
    is_resolved: boolean;
    /**
     * 检测时间
     */
    detected_at: string;
};

