/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * P5 W31-T8：单 segment BGM/SFX/ducking 偏量更新入参。
 *
 * 与 ``ChapterTimelineWrite`` 全量替换语义区分：本 DTO 仅承载 audio
 * 相关三字段且全部可选，``None`` 表示"显式清空（写 NULL）"，字段缺省
 * 表示"保持当前值不变"。校验范围与 ORM/0020 alembic 列约束一致。
 *
 * Pydantic 怎么区分"未传"与"显式 null"：路由层通过
 * ``model_dump(exclude_unset=True)`` 拿到只含被传入字段的 dict；任何
 * 未在请求体里出现的字段都不会进入 dict，从而保留 segment 已有值。
 */
export type ChapterTimelineSegmentAudioPatch = {
    /**
     * 本段 BGM FileItem ID；显式传 null 即清空当前 BGM 关联
     */
    bgm_file_id?: (string | null);
    /**
     * 本段 SFX FileItem ID；显式传 null 即清空当前 SFX 关联
     */
    sfx_file_id?: (string | null);
    /**
     * full 模式 sidechaincompress ducking 增益（dB），范围 [-30.0, 0.0]；不传则保持原值
     */
    bgm_ducking_db?: (number | null);
};

