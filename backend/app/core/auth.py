"""API Key 认证中间件。

Phase 1 认证方案：基于静态 API Key 的请求鉴权。
- 当 settings.API_KEY 为空时，跳过验证（向后兼容）。
- 支持通过 Header `X-API-Key` 或 query param `api_key` 提供密钥。
- 指定路径（文档、健康检查）始终跳过验证。
"""

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.config import settings

# 无需认证的路径集合（文档 & 健康检查）
SKIP_PATHS: set[str] = {
    "/docs",
    "/redoc",
    "/openapi.json",
    "/health",
    "/api/v1/health",
}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """基于静态 API Key 的请求认证中间件。

    行为：
    - 若 settings.API_KEY 为空字符串，则不做任何验证（完全透传）。
    - 若请求路径在 SKIP_PATHS 中，则跳过验证。
    - 否则从 Header `X-API-Key` 或 query param `api_key` 读取密钥并比对。
    - 验证失败返回 401。
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        api_key = settings.api_key

        # API_KEY 未配置时，不做验证（向后兼容）
        if not api_key:
            return await call_next(request)

        # 跳过不需要认证的路径
        if request.url.path in SKIP_PATHS:
            return await call_next(request)

        # 从 Header 或 query param 中获取提供的密钥
        provided = request.headers.get("X-API-Key") or request.query_params.get(
            "api_key"
        )

        if provided != api_key:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")

        return await call_next(request)
