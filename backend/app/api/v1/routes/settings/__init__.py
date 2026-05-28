"""``/api/v1/settings/*`` admin 路由聚合（P4 W24-T1 起）。

当前仅挂载 :mod:`api_keys`（API key 配额管理）。后续 wave 引入新的
admin 配置入口（供应商凭据、Webhook 配置等）时也会在此聚合。
"""

from fastapi import APIRouter

from app.api.v1.routes.settings import api_keys

router = APIRouter()

router.include_router(
    api_keys.router,
    prefix="/api-keys",
    tags=["settings/api-keys"],
)

__all__ = ["router"]
