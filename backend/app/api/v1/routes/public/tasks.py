"""``GET /api/v1/public/commerce/tasks/{task_id}`` —— 第三方任务状态查询（W24-T3）。

职责（保持瘦身）
----------------

1. 用 ``request.state.api_key_quota`` 拿到当前调用方的 ``api_key_hash``
   （由 :func:`app.core.api_key_auth.enforce_public_request` 中间件在
   bcrypt 校验通过后注入）；
2. 按 ``task_id`` 主键加载 :class:`app.models.task.GenerationTask`；
3. **租户隔离**：比对任务 ``payload["run_args"]["api_key_hash"]`` 与
   当前调用方 hash，不一致 / 缺失 → ``404 Not Found``（**不返回 403**，
   防止跨租户嗅探。"任务不存在"与"任务存在但不属于你"对外不可区分）；
4. 把 ORM 行收敛成 :class:`PublicTaskStatusRead` 最小 envelope 后，
   用 ``ApiResponse`` 全局响应壳返回。

为什么"跨租户必须返回 404"
--------------------------

如果对跨租户访问返回 403：

- 攻击者可借此**枚举有效 task_id** —— 看到 403 就知道"这个 ID 真实
  存在，只是不属于我"，进而可以做时间序列分析推断对手的吞吐量；
- 与本通道的"最小可观测面"原则相违背。

返回 404 的语义统一为"对你而言此任务不存在"，让任务存在与否、归属
与否都映射到同一个状态码，将信息泄露面降到最低。

为什么不在路径上扣配额
----------------------

``GET /commerce/tasks/{id}`` 是状态轮询场景，被前端高频调用；如果每
次轮询都扣一次 quota，客户端会在自己的预算上自我 DoS。延续 T24-1 的
``QUOTA_FREE_PATH_SUFFIXES = ("/status",)`` 设计思路 —— 但本端点路径
不以 ``/status`` 结尾，所以会扣配额。如果未来证明该 endpoint 同样高
频，应把 ``/commerce/tasks/`` 加入豁免白名单或在 endpoint 上显式跳过
扣减。当前 wave 暂不优化，由配额上限和 rate_per_minute 兜底。

为什么读 ``payload["run_args"]["api_key_hash"]`` 而不是单独建一列
----------------------------------------------------------------

T24-2（创建第三方任务的 POST endpoint）会把当前调用方的
``api_key_hash`` 一并写入 ``run_args``（参考
:class:`app.core.task_manager.manager.TaskManager.create` 的 payload
结构 ``{"task_class", "task_kind", "run_args": {...}}``）。复用 JSON
列既不引入 schema 变更（不需要 alembic 迁移），又能在多种 task_kind
下保持统一的归属语义。如果将来归属逻辑变得更复杂（例如多租户共享
任务），可以演进出独立的 ``owner_api_key_hash`` 列再做一次性回填。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.task import GenerationTask
from app.schemas.common import ApiResponse, success_response
from app.schemas.public.task_status import PublicTaskStatusRead

router = APIRouter()


def _extract_owner_hash(payload: Any) -> str | None:
    """从任务 ``payload`` 中读出归属调用方的 ``api_key_hash``。

    :class:`app.core.task_manager.manager.TaskManager.create` 把外部入参
    序列化成 ``{"task_class", "task_kind", "run_args": {...}}``。归属
    标记位于 ``run_args["api_key_hash"]``。本函数对任意层级的非字典
    取值都安全降级为 ``None``，避免对手通过构造异常 payload 让接口
    抛 500 间接探测内部结构。

    Args:
        payload: ``GenerationTask.payload`` 列原始值；正常情况下是
            ``dict``，但 SQLite/JSON 列在历史脏数据下可能是其它类型。

    Returns:
        归属调用方 ``api_key_hash``；任何异常路径（结构不符 / 字段缺失
        / 非字符串）一律返回 ``None``，让上游按"未归属"处理（即"对当
        前调用方不可见"）。
    """

    if not isinstance(payload, dict):
        return None
    run_args = payload.get("run_args")
    if not isinstance(run_args, dict):
        return None
    candidate = run_args.get("api_key_hash")
    return candidate if isinstance(candidate, str) and candidate else None


def _extract_result_file_id(result: Any) -> str | None:
    """从任务 ``result`` 中读出 ``result_file_id``（若存在）。

    本 endpoint 只暴露"产物为单文件"的情形；当 worker 层把 file id 写
    入 ``result["file_id"]`` 时回传给调用方，便于其调用文件下载接口。
    其它结构（多文件、嵌套对象等）一律降级为 ``None``——SaaS 调用方
    不应在公开通道里看到内部 result schema 的细节，需要时由专属接口
    暴露。
    """

    if not isinstance(result, dict):
        return None
    candidate = result.get("file_id")
    return candidate if isinstance(candidate, str) and candidate else None


def _to_public_view(task: GenerationTask) -> PublicTaskStatusRead:
    """把 ORM 行投影成最小 envelope。

    保持本函数纯函数 + 无 DB 依赖，方便后续在测试里独立验证投影逻辑
    （边界值、空字段降级行为等）。
    """

    status_value = task.status.value if hasattr(task.status, "value") else str(task.status)
    return PublicTaskStatusRead(
        status=status_value,
        progress=int(task.progress or 0),
        result_file_id=_extract_result_file_id(task.result),
        error=task.error or "",
    )


@router.get(
    "/{task_id}",
    response_model=ApiResponse[PublicTaskStatusRead],
    summary="第三方任务状态查询（公开通道，租户隔离）",
)
async def get_public_task_status(
    request: Request,
    task_id: str = Path(..., min_length=1, description="任务 ID（GenerationTask.id）"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PublicTaskStatusRead]:
    """查询当前 API key 自己提交的任务状态。

    分支顺序（与对外契约严格对齐）：

    1. 中间件已保证 ``request.state.api_key_quota`` 必然存在且 active；
       若中间件被绕过（例如未来误删），这里仍按 401 抛出，让调用方
       拿到一致的错误信号。
    2. 任务不存在 → 404；
    3. 任务存在但归属其他 ``api_key_hash`` → 同样 404（防嗅探，参见
       模块 docstring）；
    4. 归属一致 → 投影为 :class:`PublicTaskStatusRead` 后返回 200。

    Args:
        request: FastAPI 请求对象，承载中间件注入的 ``api_key_quota``。
        task_id: ``GenerationTask`` 主键。
        db: 数据库会话（``get_db`` 依赖注入，路由结束时自动 commit）。

    Returns:
        ``ApiResponse[PublicTaskStatusRead]`` 包裹的最小任务视图。
    """

    quota = getattr(request.state, "api_key_quota", None)
    if quota is None:
        # 防御性兜底：理论上中间件已经保证非空。
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    caller_hash = quota.api_key_hash

    task = await db.get(GenerationTask, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    owner_hash = _extract_owner_hash(task.payload)
    if owner_hash != caller_hash:
        # 跨租户访问统一回 404，不区分"未归属"与"归属他人"，避免嗅探。
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    return success_response(_to_public_view(task))
