/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { Platform } from './Platform';
/**
 * 部分更新一条 StoryOutcome（PATCH）—— 全字段可选。
 *
 * 通过 ``model_dump(exclude_unset=True)`` 只取请求中显式传入的字段，
 * 不会把 ``None`` 误覆盖到既有非空字段（例如 ``recorded_at``）。
 *
 * ``variant_id`` 不允许通过 PATCH 修改：变更归属应由"删除 + 重建"
 * 完成，避免静默改写历史记录的语义。
 */
export type StoryOutcomeUpdate = {
    platform?: (Platform | null);
    plays?: (number | null);
    completion_rate_3s?: (number | null);
    completion_rate_full?: (number | null);
    interactions?: (number | null);
    cart_clicks?: (number | null);
    orders?: (number | null);
    gmv?: (number | null);
    notes?: (string | null);
    raw_payload?: (Record<string, any> | null);
    recorded_at?: (string | null);
};

