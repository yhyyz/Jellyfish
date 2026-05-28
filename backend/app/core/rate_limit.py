"""API 限流配置（W24-T4：per-key 限流）。

slowapi 的 key_func 控制限流桶的划分维度。本模块在 W24-T4 之后采用
**复合 key**：

- ``/public/*`` 路径：以 ApiKey 的 bcrypt hash 作为限流 key，让每个
  第三方 SaaS 调用方按自身 ``rate_per_minute`` 隔离计数；
- 其它路径（含 ``/api/v1/*`` admin、``/health``、``/docs`` 等）：
  仍按 ``get_remote_address`` 即 IP 取桶，保留 P1 行为。

关于「per-key 限速值如何流到 ``@limiter.limit`` 装饰器」：

    slowapi 的 ``LimitGroup`` 不会把 ``Request`` 直接喂给 limit
    provider；它支持的协议是「provider 接收一个名为 ``key`` 的形参，
    形参值由 ``key_function(request)`` 给出」。因此本模块把 key 设
    计成 ``apikey:<hash>:<rate>`` 的复合串，:func:`per_key_rate_limit`
    再从 key 末段解析出 ``rate_per_minute``。这样既不破坏 slowapi 的
    既有契约，也避免把 ``request`` 状态额外塞进全局变量或 storage。

依赖契约：
    ``request.state.api_key_quota`` 由
    :func:`app.core.api_key_auth.enforce_public_request` 注入。当
    ``/public/*`` 请求未经 ApiKey 认证（理论上中间件会先 401，但路
    径白名单或子应用可能跳过）时，回退到 IP 计数，避免 ``None``
    污染 limiter storage。
"""

from fastapi import FastAPI, Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.api_key_auth import is_public_path

DEFAULT_RATE_PER_MINUTE = 200
"""``/public/*`` 异常路径或缺失 quota 时使用的兜底速率。"""

_PUBLIC_KEY_PREFIX = "apikey:"


def composite_key_func(request: Request) -> str:
    """根据请求路径选择限流桶的取键方式。

    Returns:
        - ``/public/*`` 且已注入 api_key_quota：返回
          ``"apikey:<bcrypt_hash>:<rate_per_minute>"``，把 hash 与
          速率一起编进 key。同 hash 同速率的请求落入同一限流桶；
          ``rate_per_minute`` 改值（admin 调上限）会自然进入新桶，
          老桶在 1 分钟后过期。
        - 其它情况：返回客户端远端 IP。
    """

    if is_public_path(request.url.path):
        quota = getattr(request.state, "api_key_quota", None)
        api_key_hash = getattr(quota, "api_key_hash", None)
        if api_key_hash:
            rate = getattr(quota, "rate_per_minute", None) or DEFAULT_RATE_PER_MINUTE
            return f"{_PUBLIC_KEY_PREFIX}{api_key_hash}:{int(rate)}"
    return get_remote_address(request)


def per_key_rate_limit(key: str) -> str:
    """slowapi ``@limiter.limit(...)`` 动态参数。

    Args:
        key: 由 :func:`composite_key_func` 返回的限流键。当形如
            ``"apikey:<hash>:<rate>"`` 时取末段作为限速值；其它情
            况（IP / 异常）返回全局默认速率。

    Returns:
        slowapi 可解析的限速字符串，例如 ``"60/minute"``。
    """

    if isinstance(key, str) and key.startswith(_PUBLIC_KEY_PREFIX):
        suffix = key.rsplit(":", 1)[-1]
        if suffix.isdigit() and int(suffix) > 0:
            return f"{int(suffix)}/minute"
    return f"{DEFAULT_RATE_PER_MINUTE}/minute"


limiter = Limiter(
    key_func=composite_key_func,
    default_limits=[f"{DEFAULT_RATE_PER_MINUTE}/minute"],
)


def setup_rate_limit(app: FastAPI) -> None:
    """注册限流中间件到 FastAPI 应用。

    将 limiter 挂载到 ``app.state`` 并注册 429 异常处理器。

    Args:
        app: FastAPI 应用实例。
    """
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


__all__ = [
    "DEFAULT_RATE_PER_MINUTE",
    "composite_key_func",
    "limiter",
    "per_key_rate_limit",
    "setup_rate_limit",
]
