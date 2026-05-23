"""API 限流配置。

使用 slowapi 为 FastAPI 提供全局请求速率限制，
防止单一客户端过度消耗服务器资源或进行暴力攻击。
"""

from fastapi import FastAPI
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# 全局限流器实例，默认每分钟 200 次请求（按客户端 IP 区分）。
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])


def setup_rate_limit(app: FastAPI) -> None:
    """注册限流中间件到 FastAPI 应用。

    将 limiter 挂载到 app.state 并注册超限异常处理器，
    使得超出速率限制时返回 429 Too Many Requests。

    Args:
        app: FastAPI 应用实例。
    """
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
