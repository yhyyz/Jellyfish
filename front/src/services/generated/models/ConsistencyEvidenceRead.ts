/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 分镜视觉一致性证据响应。
 *
 * 仅暴露读所需的字段，不在响应里塞 reason / debug 信息（保留 sidecar
 * debug 走 task system 路径）。
 */
export type ConsistencyEvidenceRead = {
    /**
     * 镜头 ID
     */
    shot_id: string;
    /**
     * DINOv2 cosine similarity（[-1, 1]，常落 [0, 1]）；NULL 表示未跑过 / 缺 reference / sidecar 不可达
     */
    score?: (number | null);
    /**
     * 色档：green(>=0.85) / amber([0.75,0.85)) / red(<0.75) / unknown(score=null)
     */
    status: 'green' | 'amber' | 'red' | 'unknown';
    /**
     * 抽样帧 URL 列表（最多 6 张）；当前从 Shot 关联 ProductImage 拼装作为视觉证据样本，未来可切换为 worker 持久化的真实抽样帧
     */
    sampled_frame_urls?: Array<string>;
    /**
     * 参考图 URL；与 worker 一致取 FRONT / THREE_QUARTER 优先级，缺失时为 None
     */
    reference_image_url?: (string | null);
    /**
     * 参考图视角（front / three_quarter / ...），便于 UI 标注
     */
    reference_view_angle?: (string | null);
    /**
     * 已重试次数；T27-2 引入重试机制后会写入实际值，未引入时保持 None 占位（前端按 None 隐藏 '已重试 N 次' 标签）
     */
    retry_count?: (number | null);
};

