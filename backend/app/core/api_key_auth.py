"""``/public/*`` per-key bcrypt 认证 + 原子配额扣减（P4 W24-T1）。

本模块承担两件事：

1. **bcrypt 校验**：将请求 ``X-API-Key`` header 的明文与
   :class:`app.models.api_quota.ApiKeyQuota.api_key_hash` 列做 bcrypt
   验证，命中即对应到唯一一条配额行；
2. **原子配额扣减**：用一条 ``UPDATE ... WHERE consumed_today <
   daily_limit`` SQL 完成「先判后扣」的原子操作，杜绝并发竞态。

为什么和 :mod:`app.core.auth` 分两份文件：

    :mod:`app.core.auth` 是早期 P1 落地的「静态单 key」中间件，逻辑
    简单、面向 ``/api/v1/*`` admin 内部网关；本模块面向 P3+ 第三方
    SaaS 调用入口（``/public/*``），逻辑明显更重（bcrypt + 配额 +
    Retry-After 协议），独立成模块便于安全审计与单测覆盖。

调用约定：

- 中间件入口：:func:`enforce_public_request` —— 直接挂在
  :class:`ApiKeyMiddleware` 的 ``/public/*`` 分支；
- 单测/route 内手动校验入口：:func:`authenticate_request`，可在路由
  层显式注入；
- 原子扣减：:func:`consume_quota`，可被任何业务 worker 借用做幂等
  消耗（例如离线导出、批量任务计费）。

错误响应：

- 401：缺失或无效 ``X-API-Key``；
- 403：key 已被 revoke（``is_active=False``）；
- 429：配额耗尽，附带 ``Retry-After`` 头（默认 24 小时秒数）。
"""

from __future__ import annotations

from typing import Awaitable, Callable

import bcrypt
from fastapi import HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse, Response

from app.core.db import async_session_maker
from app.models.api_quota import ApiKeyQuota
from app.services.api_quota.quota_service import BCRYPT_COST  # re-export for tests

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

PUBLIC_PATH_PREFIX = "/public/"
"""``/public/*`` 路径前缀。

任何 ``request.url.path.startswith(PUBLIC_PATH_PREFIX)`` 的请求都会
走 per-key bcrypt 校验；其它路径继续走 :mod:`app.core.auth` 的静态
单 key 兼容分支。
"""

QUOTA_FREE_PATH_SUFFIXES: tuple[str, ...] = ("/status",)
"""不参与配额扣减的 ``/public/*`` 路径后缀白名单。

- ``/status``：任务状态轮询，前端会高频拉取，扣配额会让客户端自我
  DoS。仍要求合法 ``X-API-Key``（保留可追责性），但不消耗配额。

后续如需扩展（例如 ``/healthz`` 子路径），统一加进本元组即可，避免
散落在多处魔法字符串里。
"""

QUOTA_EXHAUSTED_RETRY_AFTER_SECONDS = 24 * 60 * 60
"""配额耗尽时返回的 ``Retry-After`` 秒数。

固定 24 小时是当前 daily_limit 维度的最长重置窗口。后续若引入更细
粒度的 rate limit（rate_per_minute），应让中间件根据耗尽来源动态选
择更短的 Retry-After。
"""


# ---------------------------------------------------------------------------
# 路径分类
# ---------------------------------------------------------------------------


def is_public_path(path: str) -> bool:
    """判断请求路径是否走 per-key bcrypt 通道。"""

    return path.startswith(PUBLIC_PATH_PREFIX)


def is_quota_free_path(path: str) -> bool:
    """判断该 ``/public/*`` 路径是否豁免配额扣减。

    仅匹配后缀，避免 ``/public/foo/status/bar`` 这类伪豁免：
    ``str.endswith(...)`` 严格检查路径尾部。
    """

    return any(path.endswith(suffix) for suffix in QUOTA_FREE_PATH_SUFFIXES)


# ---------------------------------------------------------------------------
# bcrypt 校验
# ---------------------------------------------------------------------------


async def verify_api_key(
    db: AsyncSession,
    plaintext: str | None,
) -> ApiKeyQuota | None:
    """以明文匹配 ``ApiKeyQuota`` 行。

    由于 bcrypt 每次哈希都带随机盐，无法通过等值索引一步定位；只能
    扫描所有行逐一 ``bcrypt.checkpw``。对 admin 管理的少量 key（O(N)
    通常 ≤ 数十）这是可接受的折中——无需引入额外的反向查找列、保留
    "hash 即 PK"的简洁契约。

    Args:
        db: 异步会话。
        plaintext: 客户端通过 ``X-API-Key`` 提交的明文；``None`` /
            空串直接返回 ``None``。

    Returns:
        命中的 ORM 行；未命中返回 ``None``。

    关键内部逻辑：

        - 选择 *全部* 行（含 inactive），让上层根据
          ``is_active`` 单独决定 401（未知 key）/ 403（已 revoke）；
        - ``bcrypt.checkpw`` 对格式异常会抛 ``ValueError`` —— 数据
          库被人为塞坏的旧 hash 不应让整条认证管线崩溃，捕获后跳
          过该行继续匹配。
    """

    if not plaintext:
        return None
    rows = (await db.execute(select(ApiKeyQuota))).scalars().all()
    plaintext_bytes = plaintext.encode("utf-8")
    for row in rows:
        try:
            if bcrypt.checkpw(plaintext_bytes, row.api_key_hash.encode("utf-8")):
                return row
        except (ValueError, TypeError):
            # 单条 hash 格式异常 → 跳过，不影响其它候选
            continue
    return None


# ---------------------------------------------------------------------------
# 原子配额扣减
# ---------------------------------------------------------------------------


async def consume_quota(db: AsyncSession, api_key_hash: str) -> bool:
    """原子地把 ``consumed_today`` 自增 1（仅当未触顶且仍 active）。

    SQL（PostgreSQL/MySQL/SQLite 通用）：

    .. code-block:: sql

        UPDATE api_key_quotas
        SET consumed_today = consumed_today + 1
        WHERE api_key_hash = :id
          AND is_active = TRUE
          AND consumed_today < daily_limit;

    数据库层「先判后扣」保证多并发下不会出现 ``consumed_today >
    daily_limit``。

    Args:
        db: 异步会话；执行完成后会 ``commit()`` 落库。
        api_key_hash: 目标 key 的 bcrypt hash（主键）。

    Returns:
        ``True``：成功扣减一次配额；
        ``False``：配额已耗尽或 key 已 revoke（``rowcount == 0``）。
        上层据此决定是否回 429。

    关键内部逻辑：

        - ``execution_options(synchronize_session=False)``：跳过 ORM
          identity map 同步（本调用只关心 rowcount，无需把 in-memory
          实例改回 stale 状态）。
        - ``await db.commit()``：让自增立即可被其它会话观测，避免
          test fixture 端拿到旧值。
    """

    stmt = (
        update(ApiKeyQuota)
        .where(
            ApiKeyQuota.api_key_hash == api_key_hash,
            ApiKeyQuota.is_active.is_(True),
            ApiKeyQuota.consumed_today < ApiKeyQuota.daily_limit,
        )
        .values(consumed_today=ApiKeyQuota.consumed_today + 1)
        .execution_options(synchronize_session=False)
    )
    result = await db.execute(stmt)
    await db.commit()
    return (result.rowcount or 0) > 0


# ---------------------------------------------------------------------------
# 综合认证：bcrypt + 状态判定 + 配额扣减
# ---------------------------------------------------------------------------


async def authenticate_request(
    db: AsyncSession,
    plaintext: str | None,
    *,
    deduct_quota: bool = True,
) -> ApiKeyQuota:
    """完整的 ``/public/*`` 入口认证流程。

    分支顺序：

    1. 明文为空 → 401（缺 ``X-API-Key`` 头）；
    2. bcrypt 不匹配 → 401（无效 key）；
    3. ``is_active=False`` → 403（已 revoke）；
    4. ``deduct_quota=True`` 时执行原子扣减，``False`` 表示走豁免
       路径（如 ``/public/.../status``）；
    5. 扣减失败（rowcount=0）→ 429 + ``Retry-After``。

    Returns:
        已通过校验的 ``ApiKeyQuota`` 行。``deduct_quota=True`` 路径
        会 ``refresh`` 行以反映最新 ``consumed_today``。
    """

    if not plaintext:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")

    matched = await verify_api_key(db, plaintext)
    if matched is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    if not matched.is_active:
        raise HTTPException(status_code=403, detail="API key is inactive")

    if not deduct_quota:
        return matched

    if not await consume_quota(db, matched.api_key_hash):
        raise HTTPException(
            status_code=429,
            detail="API quota exceeded",
            headers={"Retry-After": str(QUOTA_EXHAUSTED_RETRY_AFTER_SECONDS)},
        )
    await db.refresh(matched)
    return matched


# ---------------------------------------------------------------------------
# Middleware integration
# ---------------------------------------------------------------------------


async def enforce_public_request(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """``/public/*`` 路径的中间件分派点。

    在请求到达路由前完成 bcrypt 校验 + 可选配额扣减；失败时直接以
    :class:`JSONResponse` 返回，**不**再走 FastAPI 的全局异常处理器
    （middleware 内 raise HTTPException 行为依赖 starlette 版本，统
    一返回 JSONResponse 更确定性）。

    Args:
        request: 当前 starlette 请求。
        call_next: 中间件链下游调用。

    Returns:
        - 校验通过：直接转发给 ``call_next``；
        - 校验失败：401/403/429 之一的 :class:`JSONResponse`，body
          仍遵循 ``{code, message, data, meta}`` 全局响应壳。

    关键内部逻辑：

        - 优先使用 ``request.app.state.session_maker``（测试用例可以
          注入 in-memory engine 的 sessionmaker），缺省回落到全局
          :func:`app.core.db.async_session_maker`。这条 seam 让
          middleware 行为在单测中可被精确观测。
    """

    plaintext = request.headers.get("X-API-Key")
    deduct = not is_quota_free_path(request.url.path)
    session_maker = (
        getattr(request.app.state, "session_maker", None)
        or async_session_maker
    )
    try:
        async with session_maker() as db:
            await authenticate_request(
                db, plaintext, deduct_quota=deduct
            )
    except HTTPException as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.status_code,
                "message": str(exc.detail),
                "data": None,
                "meta": None,
            },
            headers=exc.headers or {},
        )

    return await call_next(request)


__all__ = [
    "BCRYPT_COST",
    "PUBLIC_PATH_PREFIX",
    "QUOTA_EXHAUSTED_RETRY_AFTER_SECONDS",
    "QUOTA_FREE_PATH_SUFFIXES",
    "authenticate_request",
    "consume_quota",
    "enforce_public_request",
    "is_public_path",
    "is_quota_free_path",
    "verify_api_key",
]
