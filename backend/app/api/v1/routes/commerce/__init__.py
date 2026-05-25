"""``/api/v1/commerce`` 路由聚合（W6-T3）。

P1 阶段聚焦 3 个异步任务入口：商品信息抽取、剧情脚本生成、合规检查。
后续 wave 会继续扩展商品 / 故事项目等 CRUD 端点。

按照分层约定，路由层只做收参 + 调 service + 包装 ``ApiResponse``，业务
逻辑全部下沉到 ``app/services/commerce``。
"""

from fastapi import APIRouter

from app.api.v1.routes.commerce import tasks

router = APIRouter()

router.include_router(tasks.router, tags=["commerce/tasks"])

__all__ = ["router"]
