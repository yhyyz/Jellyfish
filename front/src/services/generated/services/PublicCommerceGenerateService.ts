/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_PublicGenerateResponse_ } from '../models/ApiResponse_PublicGenerateResponse_';
import type { PublicGenerateRequest } from '../models/PublicGenerateRequest';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class PublicCommerceGenerateService {
    /**
     * 第三方调用入口：提交一次剧情带货生成请求（公开通道）
     * 同步入队 + 返回 ``task_id``，让第三方 SaaS 走异步轮询模型。
     *
     * 分支顺序（与对外契约严格对齐）：
     *
     * 1. 中间件已保证 ``request.state.api_key_quota`` 必然存在且 active；
     * 若被误删，这里仍按 401 抛出，让调用方拿到一致的错误信号。
     * 2. ``Product`` / ``StoryFormula`` 不存在 → 404；可选的
     * ``PlatformExportPreset`` 若提供也必须存在，否则同样 404。
     * 3. 透传到 :class:`CommerceTaskDispatchService`，把 ``api_key_hash``
     * 写入 ``run_args`` —— **关键**，这是 T24-3 跨租户隔离的前置。
     * 4. 严格遵守 W19b 的 *commit-then-send* 契约：先 ``await db.commit()``
     * 再 ``dispatch_after_commit``，避免 ``fast`` / ``slow`` 队列上的
     * worker 在外层事务尚未 commit 时拿到 ``None``（B2 race）。
     *
     * Args:
     * request: FastAPI 请求对象，承载中间件注入的 ``api_key_quota``。
     * body: 经 :class:`PublicGenerateRequest` 校验过的请求体。
     * db: 数据库会话（``get_db`` 依赖注入）。
     *
     * Returns:
     * ``ApiResponse[PublicGenerateResponse]`` 包裹的最小信封。
     *
     * Raises:
     * HTTPException: 401（中间件意外失效）、404（product / formula /
     * preset 不存在）。
     * @returns ApiResponse_PublicGenerateResponse_ Successful Response
     * @throws ApiError
     */
    public static submitPublicGenerateApiV1PublicCommerceGeneratePost({
        requestBody,
    }: {
        requestBody: PublicGenerateRequest,
    }): CancelablePromise<ApiResponse_PublicGenerateResponse_> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/public/commerce/generate',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
