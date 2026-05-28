/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { VoiceCloneStatus } from './VoiceCloneStatus';
/**
 * 单条音色状态查询响应（``GET /status``）。
 *
 * 用于前端 VoicePackLibrary 自动轮询 ``deploying`` 行；``ready`` /
 * ``failed`` 终态后停止轮询。
 */
export type CustomVoiceStatusResponse = {
    voice_pack_id: string;
    clone_status: VoiceCloneStatus;
    /**
     * DashScope 返回的 voice_id；ready 后填充
     */
    provider_voice_id?: (string | null);
    /**
     * failed 时的失败原因（取 description 末尾备注）
     */
    failure_reason?: (string | null);
    /**
     * ready 时的完成时间戳；其他状态为 NULL
     */
    cloned_at?: (string | null);
};

