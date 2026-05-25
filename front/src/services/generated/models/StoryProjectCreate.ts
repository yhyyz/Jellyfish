/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { CommerceStoryConfigBase } from './CommerceStoryConfigBase';
import type { ProjectStyle } from './ProjectStyle';
import type { ProjectVisualStyle } from './ProjectVisualStyle';
/**
 * 创建 commerce_story 项目请求体。
 *
 * 同时承载 Project 核心字段与 CommerceStoryConfig 字段；服务层在单事务
 * 内完成两表 INSERT，并强制 ``kind=commerce_story``。
 */
export type StoryProjectCreate = {
    /**
     * 项目 ID（业务方生成或外部生成）
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
    style?: ProjectStyle;
    /**
     * 画面表现形式（真人/动漫等）
     */
    visual_style?: ProjectVisualStyle;
    /**
     * 随机种子
     */
    seed?: number;
    /**
     * 是否统一风格（跨章节）
     */
    unify_style?: boolean;
    /**
     * 进度百分比
     */
    progress?: number;
    /**
     * 项目级默认视频比例
     */
    default_video_ratio?: (string | null);
    /**
     * 聚合统计（JSON）
     */
    stats?: Record<string, any>;
    /**
     * 带货项目专属配置
     */
    config?: CommerceStoryConfigBase;
};

