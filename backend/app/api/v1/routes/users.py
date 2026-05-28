"""``/api/v1/users/*`` 用户自查询路由（P5 W32-followup 引入）。

为什么存在：
    ``/api/v1/settings/users/*`` 整子树是 admin-only（W32-T10 已落地的
    ``router-level dependencies=[Depends(require_admin)]`` 守卫），但
    任何已登录用户都需要查自己的 profile —— 前端 ``AuthContext``
    登录成功后必须立即调用 ``/me`` 拿真实 ``role``，否则只能 hardcode
    fallback 为 ``admin``，会导致 member 用户看到不该看到的 admin
    入口（虽然 backend ``require_admin`` 守卫会拦 403，但前端体验差）。

    所以独立成 ``/api/v1/users`` 路由树，仅用 ``Depends(get_current_user)``
    守护，不在 admin-only 子树之内。

实现遵循 AGENTS.md §4：
- 路由层只做收参（``Depends(get_current_user)``）/ 响应包装；
- 业务校验已在 :func:`app.dependencies.get_current_user` 完成
  （JWT 解码、用户存在性、is_active 判断、Stage-1 静态 fallback）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.auth.user import UserRead
from app.schemas.common import ApiResponse, success_response


router = APIRouter()


@router.get(
    "/me",
    response_model=ApiResponse[UserRead],
    summary="查询当前登录用户 profile",
)
async def read_users_me(
    current_user: User = Depends(get_current_user),
) -> ApiResponse[UserRead]:
    """返回当前 JWT（或 Stage-1 静态 fallback）关联的 :class:`User`。

    任何已登录用户都可调用（不限制 role），前端 ``AuthContext`` 用此
    端点在登录后立即拉真实 role，避免硬编码导致 member 看到 admin 入口。

    Stage-1 静态 fallback 行为：
        ``settings.jwt_fallback_to_static=True`` 且 ``Authorization``
        头为 ``Bearer <settings.api_key>`` 时，返回内存虚拟 admin
        （``id=__static_fallback__``，``role=ADMIN``，``is_active=True``）。
        这是有意义的 —— 前端通过 fallback 登录时也能拿到 ``role=admin``。

    Returns:
        :class:`ApiResponse[UserRead]`: 当前用户的 ``id`` / ``username``
        / ``email`` / ``role`` / ``is_active`` / ``created_at`` /
        ``updated_at``。响应不会暴露 ``hashed_password``。
    """

    return success_response(UserRead.model_validate(current_user))
