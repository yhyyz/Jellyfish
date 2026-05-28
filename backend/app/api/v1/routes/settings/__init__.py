"""``/api/v1/settings/*`` admin 路由聚合（P4 W24-T1 起；P5 W32-T10 加 users）。

挂载点：
- ``/api-keys`` (W24-T1)
- ``/users`` (W32-T10) — RBAC 用户管理
"""

from fastapi import APIRouter

from app.api.v1.routes.settings import api_keys, users

router = APIRouter()

router.include_router(
    api_keys.router,
    prefix="/api-keys",
    tags=["settings/api-keys"],
)

router.include_router(
    users.router,
    prefix="/users",
    tags=["settings/users"],
)

__all__ = ["router"]
