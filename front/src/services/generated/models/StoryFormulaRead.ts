/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { FormulaRegion } from './FormulaRegion';
import type { StoryFormulaStructureRead } from './StoryFormulaStructureRead';
/**
 * StoryFormula 只读响应。
 *
 * 字段与 ORM 列对齐；``structure`` 单独从 JSON 列拆解出嵌套结构，便于
 * 前端直接渲染节拍。``risk_flags`` / ``use_cases`` / ``avoid_cases``
 * 保持原始 ``list[str]``，与种子数据格式一致。
 */
export type StoryFormulaRead = {
    /**
     * 公式 ID（如 underdog_triumph）
     */
    id: string;
    /**
     * 中文名称
     */
    name: string;
    /**
     * 适用地域：cn / global
     */
    region: FormulaRegion;
    /**
     * 分类标签
     */
    category: string;
    /**
     * 完整 beat 结构（含 beats 数组、镜头数与时长范围）
     */
    structure: StoryFormulaStructureRead;
    /**
     * 合规风险标记数组
     */
    risk_flags?: Array<string>;
    /**
     * 完整示例剧本（变量化）
     */
    sample_dialog: string;
    /**
     * 典型时长（秒）
     */
    typical_duration_sec: number;
    /**
     * 典型镜头数
     */
    typical_shot_count: number;
    /**
     * 心理学原理：为什么有效
     */
    psychology: string;
    /**
     * 适用场景
     */
    use_cases?: Array<string>;
    /**
     * 禁忌场景
     */
    avoid_cases?: Array<string>;
    /**
     * 绑定的提示词模板 ID
     */
    prompt_template_id: string;
    /**
     * 系统模板标记，应用层不可删除
     */
    is_system: boolean;
    /**
     * UI 显示排序（升序）
     */
    sort_order: number;
};

