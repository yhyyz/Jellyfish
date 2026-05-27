/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * ``POST /api/v1/commerce/chapter-av-plan`` 请求体（P3 W17）。
 *
 * 触发 ``chapter_av_plan`` worker：对章节内所有 ``ShotDialogLine`` 跑
 * Decision F 决策树（estimate → speed_adjust → llm_rewrite → hold），
 * keep_native shot 跳过整树。
 */
export type ChapterAvPlanRequest = {
    /**
     * 目标章节 ID
     */
    chapter_id: string;
};

