"""API key 配额服务（P4 W24-T1）。

负责 :class:`app.models.api_quota.ApiKeyQuota` 表的 admin 侧 CRUD：

- :func:`create_api_key`：随机生成明文 key、bcrypt 哈希落库，返回
  ``(plaintext, ApiKeyQuota)``。**明文仅本次返回**，后端不存储；
- :func:`list_api_keys`：列出所有 key（默认排除已 revoke 的 inactive
  行）；
- :func:`revoke_api_key`：将指定 key 标记为 ``is_active=False``（不
  物理删除，保留历史配额计数与可观测性）；
- :func:`get_usage`：按 hash 查询单条 key 的实时用量。

设计要点：

1. **明文生成格式**：``jellyfish_<base64url(secrets.token_bytes(32))>``，
   保证 ≥ 32 字节熵 + 易识别的供应商前缀；
2. **bcrypt cost factor = 12**：满足业界最低安全门槛（2023+ OWASP
   推荐），对应 ~250ms 单次 verify 时延；
3. **明文从不入库**：``ApiKeyQuota`` 表只存 hash；
   :func:`create_api_key` 唯一返回 plaintext 的入口在管理面板创建
   时一次性下发；
4. **revoke = 软删**：保留 ``consumed_today`` / ``consumed_this_month``
   计数与历史，便于事后审计；如需彻底清理由独立 GC 任务负责。

为什么独立成 ``app.services.api_quota`` 而不是塞进 ``services/
common``：

    quota 子域有自己的安全模型（明文一次性返回、原子扣减、bcrypt
    校验），与 ``common`` 通用 CRUD 的语义差距明显，独立目录便于
    后续扩展 rate limit 策略 / 审计日志 / Webhook 配额耗尽通知。
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_quota import ApiKeyQuota


# ---------------------------------------------------------------------------
# 常量：bcrypt 成本与明文格式
# ---------------------------------------------------------------------------

BCRYPT_COST = 12
"""bcrypt cost factor。

12 是 2023+ OWASP 推荐的最低值；提高到 13/14 会显著拖慢登录，对
admin-managed API key（创建频率极低、verify 延迟可接受）来说 12
是合适的安全/性能折中。
"""

KEY_PLAINTEXT_PREFIX = "jellyfish_"
"""明文 key 前缀。

让 SaaS 调用方一眼就能识别这是 Jellyfish 颁发的 key（避免误用 OpenAI
key），同时也给后续在日志中做正则脱敏提供锚点。
"""


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _generate_plaintext_key() -> str:
    """生成形如 ``jellyfish_<base64url_random>`` 的明文 key。

    ``secrets.token_urlsafe(32)`` 给出 32 字节熵（约 256 bit），编码
    后约 43 字符。加上前缀总长 ~53 字符，URL-safe，可直接作为
    ``X-API-Key`` header 值。
    """

    return KEY_PLAINTEXT_PREFIX + secrets.token_urlsafe(32)


def _hash_plaintext(plaintext: str) -> str:
    """bcrypt 哈希明文。

    使用 ``BCRYPT_COST`` 常量控制计算成本；返回 60 字符的标准 bcrypt
    串（``$2b$12$...``），落 ``ApiKeyQuota.api_key_hash`` 列。
    """

    return bcrypt.hashpw(
        plaintext.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_COST)
    ).decode("utf-8")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def create_api_key(
    db: AsyncSession,
    *,
    description: str = "",
    daily_limit: int = 1000,
    monthly_limit: int = 30000,
    rate_per_minute: int = 60,
) -> tuple[str, ApiKeyQuota]:
    """创建一条新的 ``ApiKeyQuota`` 记录。

    Args:
        db: 当前请求绑定的 ``AsyncSession``，由路由层 ``Depends(get_db)``
            注入。
        description: 备注（管理面板辨认用途）。
        daily_limit: 日调用上限。
        monthly_limit: 月调用上限。
        rate_per_minute: 每分钟限流上限。

    Returns:
        ``(plaintext_key, ApiKeyQuota)`` 二元组：

        - ``plaintext_key``：明文 key，**仅本次可见**，调用方必须自行
          保管。后端不会再持有任何明文。
        - ``ApiKeyQuota``：刚刚 flush 的 ORM 行（``api_key_hash`` /
          ``created_at`` / ``updated_at`` 已就位）。

    关键内部逻辑：

        1. 生成明文 → bcrypt 哈希 → 落 ``api_key_hash`` 主键；
        2. ``last_reset_daily`` / ``last_reset_monthly`` 写入今日，
           后续日/月度重置任务以此为参照；
        3. ``await db.flush()`` 之后再 ``refresh()`` 拉回 server_default
           填充的字段，避免后续 ``model_validate`` 缺字段。
    """

    plaintext = _generate_plaintext_key()
    api_key_hash = _hash_plaintext(plaintext)
    today = datetime.now(UTC).date()
    row = ApiKeyQuota(
        api_key_hash=api_key_hash,
        description=description,
        daily_limit=daily_limit,
        monthly_limit=monthly_limit,
        rate_per_minute=rate_per_minute,
        consumed_today=0,
        consumed_this_month=0,
        last_reset_daily=today,
        last_reset_monthly=today,
        is_active=True,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return plaintext, row


async def list_api_keys(
    db: AsyncSession,
    *,
    include_inactive: bool = False,
) -> list[ApiKeyQuota]:
    """列出所有 API key（默认排除 ``is_active=False`` 行）。

    Args:
        db: 异步会话。
        include_inactive: 默认 ``False`` 仅列活跃 key；管理员需要查看
            历史已 revoke 的记录时显式置 ``True``。

    Returns:
        按 ``created_at DESC`` 排序的 ORM 行列表。
    """

    stmt = select(ApiKeyQuota)
    if not include_inactive:
        stmt = stmt.where(ApiKeyQuota.is_active.is_(True))
    stmt = stmt.order_by(ApiKeyQuota.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def revoke_api_key(
    db: AsyncSession,
    *,
    api_key_hash: str,
) -> ApiKeyQuota | None:
    """将指定 key 标记为 ``is_active=False``。

    使用软删而非物理删除：保留历史配额计数与可观测性。重复 revoke
    幂等。

    Args:
        db: 异步会话。
        api_key_hash: 目标 key 的 bcrypt hash（主键值）。

    Returns:
        被 revoke 的 ORM 行；若 hash 不存在返回 ``None``，由上层决定
        如何回 404。
    """

    row = await db.get(ApiKeyQuota, api_key_hash)
    if row is None:
        return None
    row.is_active = False
    await db.flush()
    await db.refresh(row)
    return row


async def get_usage(
    db: AsyncSession,
    *,
    api_key_hash: str,
) -> ApiKeyQuota | None:
    """返回单条 key 的实时配额计数。

    与 ``list_api_keys`` 不同，本接口允许查询已 revoke 的 key（用于
    事后审计）；调用方在路由层根据 ``is_active`` 决定是否给出告警。
    """

    return await db.get(ApiKeyQuota, api_key_hash)


__all__ = [
    "BCRYPT_COST",
    "KEY_PLAINTEXT_PREFIX",
    "create_api_key",
    "get_usage",
    "list_api_keys",
    "revoke_api_key",
]
