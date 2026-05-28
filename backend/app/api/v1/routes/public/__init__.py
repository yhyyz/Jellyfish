"""``/api/v1/public/*`` 子路由聚合（P4 W24）。

本子包承载所有走 per-key bcrypt + 配额扣减的第三方公开接口。挂载点
是 ``/api/v1/public``（同时保留根级 ``/public/*`` 历史路径作为向后
兼容入口；统一在 :func:`app.core.api_key_auth.is_public_path` 命中
两种前缀）。

按业务模块组织 sub-router：

- ``tasks`` —— 第三方任务状态查询（W24-T3）。

未来 wave（如 ``commerce/products/extract`` 公开版、文件下载等）继续
在此聚合，避免散落在 ``commerce/*`` 内、与 admin 入口耦合到一起。
"""

from fastapi import APIRouter

from app.api.v1.routes.public import tasks

router = APIRouter()

# /commerce/tasks/{task_id} —— 第三方任务状态查询（W24-T3）
router.include_router(
    tasks.router,
    prefix="/commerce/tasks",
    tags=["public/commerce/tasks"],
)

__all__ = ["router"]
