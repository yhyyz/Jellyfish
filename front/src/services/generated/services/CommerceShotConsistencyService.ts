/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_ConsistencyEvidenceRead_ } from '../models/ApiResponse_ConsistencyEvidenceRead_';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class CommerceShotConsistencyService {
    /**
     * 分镜视觉一致性证据（score + 抽样帧 + 参考图）
     * 返回 shot_id 对应的视觉一致性证据。
     *
     * 路径参数：
     *
     * - ``shot_id``：``Shot.id``，不存在返回 404。
     *
     * 响应数据：
     *
     * - ``score``：``Shot.consistency_score``（``None`` 表示未跑 / 缺参考）。
     * - ``status``：色档字面量，按 0.85 / 0.75 阈值映射。
     * - ``sampled_frame_urls``：从关联 product 的 ProductImage 拼装的视觉证据
     * 样本（最多 6 张）；当前 worker 不持久化 ffmpeg 抽帧，待后续 wave
     * 接入持久化路径后可平滑替换。
     * - ``reference_image_url``：与 worker 同源选取（FRONT > THREE_QUARTER）。
     * - ``retry_count``：T27-2 重试机制字段；未落地时为 ``None``。
     * @returns ApiResponse_ConsistencyEvidenceRead_ Successful Response
     * @throws ApiError
     */
    public static getShotConsistencyEvidenceApiV1CommerceShotsShotIdConsistencyEvidenceGet({
        shotId,
    }: {
        shotId: string,
    }): CancelablePromise<ApiResponse_ConsistencyEvidenceRead_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/commerce/shots/{shot_id}/consistency-evidence',
            path: {
                'shot_id': shotId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
