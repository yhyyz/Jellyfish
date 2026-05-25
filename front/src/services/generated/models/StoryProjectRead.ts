/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { CommerceStoryConfigRead } from './CommerceStoryConfigRead';
import type { ProjectStyle } from './ProjectStyle';
import type { ProjectVisualStyle } from './ProjectVisualStyle';
/**
 * commerce_story 项目详情：Project 核心 + CommerceStoryConfig。
 *
 * ``config`` 可能为空：当历史数据未补齐时（理论上不应出现，但保留容
 * 错），列表 / 详情接口仍然可用。
 */
export type StoryProjectRead = {
    /**
     * 项目 ID
     */
    id: string;
    /**
     * 项目名称
     */
    name: string;
    /**
     * 项目简介
     */
    description?: string;
    /**
     * 题材/风格
     */
    style: ProjectStyle;
    /**
     * 画面表现形式
     */
    visual_style: ProjectVisualStyle;
    /**
     * 随机种子
     */
    seed: number;
    /**
     * 项目类型（固定为 commerce_story）
     */
    kind: string;
    /**
     * 是否统一风格
     */
    unify_style: boolean;
    /**
     * 进度百分比
     */
    progress: number;
    /**
     * 项目级默认视频比例
     */
    default_video_ratio?: (string | null);
    /**
     * 聚合统计
     */
    stats?: Record<string, any>;
    /**
     * 带货项目专属配置（1:1）
     */
    config?: (CommerceStoryConfigRead | null);
};

