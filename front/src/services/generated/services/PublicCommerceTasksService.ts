/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ApiResponse_PublicTaskStatusRead_ } from '../models/ApiResponse_PublicTaskStatusRead_';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class PublicCommerceTasksService {
    /**
     * 第三方任务状态查询（公开通道，租户隔离）
     * 查询当前 API key 自己提交的任务状态。
     *
     * 分支顺序（与对外契约严格对齐）：
     *
     * 1. 中间件已保证 ``request.state.api_key_quota`` 必然存在且 active；
     * 若中间件被绕过（例如未来误删），这里仍按 401 抛出，让调用方
     * 拿到一致的错误信号。
     * 2. 任务不存在 → 404；
     * 3. 任务存在但归属其他 ``api_key_hash`` → 同样 404（防嗅探，参见
     * 模块 docstring）；
     * 4. 归属一致 → 投影为 :class:`PublicTaskStatusRead` 后返回 200。
     *
     * Args:
     * request: FastAPI 请求对象，承载中间件注入的 ``api_key_quota``。
     * task_id: ``GenerationTask`` 主键。
     * db: 数据库会话（``get_db`` 依赖注入，路由结束时自动 commit）。
     *
     * Returns:
     * ``ApiResponse[PublicTaskStatusRead]`` 包裹的最小任务视图。
     * @returns ApiResponse_PublicTaskStatusRead_ Successful Response
     * @throws ApiError
     */
    public static getPublicTaskStatusApiV1PublicCommerceTasksTaskIdGet({
        taskId,
    }: {
        /**
         * 任务 ID（GenerationTask.id）
         */
        taskId: string,
    }): CancelablePromise<ApiResponse_PublicTaskStatusRead_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/public/commerce/tasks/{task_id}',
            path: {
                'task_id': taskId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
