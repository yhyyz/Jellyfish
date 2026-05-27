/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 镜头音频策略（P3 Decision D）。
 *
 * 控制视频生成阶段如何处理对白音轨：
 *
 * - silent_with_tts：默认。生成静音视频，由后续 TTS 合成对白覆盖。
 * - keep_native：保留视频生成模型自带原音，作为极少数需要原音对口型镜头的逃生口。
 */
export type AudioStrategy = 'silent_with_tts' | 'keep_native';
