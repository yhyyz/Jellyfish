/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 自定义 voice clone 训练 / 服务状态（P5 W29 引入）。
 *
 * 与 ``VoicePack.clone_status`` 列绑定，覆盖完整生命周期：
 *
 * - ``deploying``：DashScope ``create_voice`` 已下发，轮询 worker 仍在等待
 * ``query_voice`` 返回 ``status=OK``；前端展示 spinner badge。
 * - ``ready``：训练完成可用；TTS 合成路径只允许在该状态下挑选这条音色。
 * - ``failed``：DashScope 返回 ``UNDEPLOYED`` 或轮询超时（5 分钟）；前端
 * 显示红色 badge + tooltip 失败原因。
 * - ``deleted``：调用 ``delete_voice`` 已释放 DashScope 配额，DB 行保留作
 * 审计；列表 API 默认过滤掉。
 *
 * 系统级 seed 行（``is_system=TRUE``）由 alembic 0018 backfill 为
 * ``ready`` 状态，新建系统行（如 W29-T10 海外音色 seed）由调用方显式写
 * ``ready``。
 */
export type VoiceCloneStatus = 'deploying' | 'ready' | 'failed' | 'deleted';
