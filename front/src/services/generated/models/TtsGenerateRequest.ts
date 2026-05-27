/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * ``POST /api/v1/commerce/tts/generate`` 请求体（P3 W17）。
 *
 * 触发 ``tts_generate`` worker：用 CosyVoice 合成单段对白音频，落
 * FileItem + tts_cache。``cache_key = sha256(text|voice_pack_id|speed:.3f)``
 * 命中即直接复用既有音频。
 */
export type TtsGenerateRequest = {
    /**
     * 待合成文本
     */
    text: string;
    /**
     * VoicePack 主键（如 cosyvoice_v2_longxiaochun）
     */
    voice_pack_id: string;
    /**
     * 语速倍率，0.5–2.0
     */
    speed?: number;
    /**
     * 输出格式：mp3 / wav / pcm / opus
     */
    audio_format?: string;
    /**
     * 是否启用字级时间戳
     */
    enable_word_timestamps?: boolean;
};

