/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { StoryFormulaBeatRead } from './StoryFormulaBeatRead';
/**
 * ``structure`` JSON 列的结构化只读视图。
 *
 * 把数据库内 ``structure`` JSON 内容拆为类型化字段，避免前端反复做
 * 弱类型 JSON 解析。同时保留 ``Tuple`` 转 ``list[int]`` 的容忍：
 * ``bootstrap_builtin_story_formulas.to_structure_payload`` 会写入
 * ``[a, b]`` 形式（``list``），与 ORM 读出来的 JSON 表现一致。
 */
export type StoryFormulaStructureRead = {
    /**
     * 叙事节拍数组
     */
    beats?: Array<StoryFormulaBeatRead>;
    /**
     * 典型镜头数范围 [min, max]
     */
    total_shots_range?: Array<number>;
    /**
     * 典型时长范围（秒）[min, max]
     */
    duration_sec_range?: Array<number>;
};

