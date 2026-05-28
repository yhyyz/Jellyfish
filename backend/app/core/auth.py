"""API Key 认证中间件。

历史背景：

- **P1**：基于静态 ``settings.api_key`` 的全局门禁；当 ``API_KEY``
  为空时跳过校验（向后兼容）。
- **P4 W24-T1**：新增 ``/public/*`` per-key 通道，使用 bcrypt 校验
  + 原子配额扣减（参见 :mod:`app.core.api_key_auth`）。

路径分支约定：

============================  =====================================
路径前缀                      校验策略
============================  =====================================
``/docs`` / ``/redoc`` /
``/openapi.json`` / ``/health``  无需认证（始终放行）
``/api/v1/health``               无需认证
``/public/*``                    per-key bcrypt + 配额（新通道）
其它（``/api/v1/*`` 等）          静态单 key（legacy，保持不变）
============================  =====================================

为什么静态单 key 分支保持不变：

    现有部署可能已经把 ``API_KEY=...`` 配进 ``.env``，依赖该值守住
    ``/api/v1/*`` admin 入口。本次升级仅 *新增* ``/public/*`` 分支，
    不动既有契约；如未来下线静态单 key，也只需删除该分支而不影响
    SaaS 调用方。

错误响应格式：

    认证失败（401）以 :class:`JSONResponse` 直接返回，body 仍遵循
    全局 ``{code, message, data, meta}`` 响应壳。这样无论是否注册
    了全局 ``add_exception_handler(HTTPException)``，中间件层错误
    都能稳定落到客户端，便于单测 / 子应用复用。
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app.config import settings
from app.core.api_key_auth import enforce_public_request, is_public_path

SKIP_PATHS: set[str] = {
    "/docs",
    "/redoc",
    "/openapi.json",
    "/health",
    "/api/v1/health",
}


def _unauthorized_response() -> JSONResponse:
    """构造统一的 401 ``ApiResponse`` 信封。

    与 :func:`app.main.http_exception_handler` 输出格式一致，确保
    middleware 层的拒绝也能被前端按统一壳处理。
    """

    return JSONResponse(
        status_code=401,
        content={
            "code": 401,
            "message": "Invalid or missing API key",
            "data": None,
            "meta": None,
        },
    )


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """带路径分支的 API Key 认证中间件。

    分支顺序（从高到低）：

    1. ``SKIP_PATHS``：直接放行，文档与健康检查不受认证影响。
    2. ``/public/*``：交给
       :func:`app.core.api_key_auth.enforce_public_request` 走 bcrypt
       per-key 通道（含配额扣减）。
    3. 其它路径（``/api/v1/*`` 为主）：沿用 P1 静态单 key 行为。

    设计目标是保持向后兼容：现有静态 ``settings.api_key`` 不动，新通
    道独立挂载，便于回滚。
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path

        if path in SKIP_PATHS:
            return await call_next(request)

        if is_public_path(path):
            return await enforce_public_request(request, call_next)

        api_key = settings.api_key
        if not api_key:
            return await call_next(request)

        provided = request.headers.get("X-API-Key") or request.query_params.get(
            "api_key"
        )

        if provided != api_key:
            return _unauthorized_response()

        return await call_next(request)
