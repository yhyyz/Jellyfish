/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { VoiceCloneStatus } from './VoiceCloneStatus';
/**
 * 自定义音色创建立即响应 DTO（``202 Accepted``）。
 *
 * DashScope ``create_voice`` 是异步训练，调用即返回 voice_id 但状态停留
 * 在 ``DEPLOYING``；本响应回给前端 voice_pack_id（DB 行主键）+
 * ``clone_status=deploying``，前端凭它去 ``GET /status`` 轮询直到
 * ``ready`` / ``failed``。
 */
export type CustomVoiceCreateResponse = {
    /**
     * VoicePack 行主键
     */
    voice_pack_id: string;
    /**
     * 当前 clone 状态；新创建必为 deploying
     */
    clone_status: VoiceCloneStatus;
    /**
     * VoicePack 行入库时刻
     */
    created_at: string;
};

