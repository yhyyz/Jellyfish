"""配额周期性重置任务（W24-T4）。

由 RedBeat beat scheduler 按 ``crontab`` 触发：

- ``task.quota.reset_daily``：每日 00:00 项目时区重置
  ``ApiKeyQuota.consumed_today`` 为 0，并把 ``last_reset_daily``
  推进到今日；
- ``task.quota.reset_monthly``：每月 1 日 00:00 重置
  ``ApiKeyQuota.consumed_this_month`` 为 0，并推进
  ``last_reset_monthly`` 到本月 1 号。

为什么 worker 侧用同步 SQLAlchemy：
    Celery 默认 prefork 进程是同步上下文，混用 ``asyncio.run`` 在
    worker 内部容易和 ``app.core.db`` 的 async runtime 抢事件循环。
    本模块复用 :mod:`app.core.db_sync` 提供的同步 sessionmaker，简
    单可靠且不影响 admin API 的 async 路径。

只刷活跃 key：
    ``is_active=False`` 的行属于已 revoke 状态，必须保留它们的
    ``consumed_today`` / ``consumed_this_month`` 历史计数用于事后
    审计；本任务用 ``WHERE is_active = TRUE`` 做硬性过滤。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import update

from app.core.celery_app import celery_app
from app.core.db_sync import sync_session_maker
from app.models.api_quota import ApiKeyQuota


def _today() -> date:
    """返回 UTC 当前日期。

    使用 UTC 而非项目时区是刻意选择：``last_reset_*`` 列只用作幂等
    重置的水位线，时区漂移在跨日边界最多触发一次额外/缺失重置（由
    crontab 频率决定，不由列值本身决定），UTC 让多时区部署的水位
    线读起来一致。
    """

    return datetime.now(UTC).date()


def _first_of_month(d: date) -> date:
    """返回给定日期所在月的第 1 日。"""

    return d.replace(day=1)


def reset_daily_quotas_sync(session_maker: Any | None = None) -> int:
    """业务核心：把所有 active key 的 ``consumed_today`` 归零。

    Args:
        session_maker: 可注入的 sessionmaker，便于单测用 in-memory
            engine 替换。``None`` 时回落到全局
            :data:`app.core.db_sync.sync_session_maker`。

    Returns:
        受影响的行数（仅 active key），便于 worker 日志记录。
    """

    maker = session_maker or sync_session_maker
    today = _today()
    with maker() as session:
        result = session.execute(
            update(ApiKeyQuota)
            .where(ApiKeyQuota.is_active.is_(True))
            .values(consumed_today=0, last_reset_daily=today)
            .execution_options(synchronize_session=False)
        )
        session.commit()
        return int(result.rowcount or 0)


def reset_monthly_quotas_sync(session_maker: Any | None = None) -> int:
    """业务核心：把所有 active key 的 ``consumed_this_month`` 归零。

    Args:
        session_maker: 可注入的 sessionmaker，便于单测。

    Returns:
        受影响的行数（仅 active key）。
    """

    maker = session_maker or sync_session_maker
    first = _first_of_month(_today())
    with maker() as session:
        result = session.execute(
            update(ApiKeyQuota)
            .where(ApiKeyQuota.is_active.is_(True))
            .values(consumed_this_month=0, last_reset_monthly=first)
            .execution_options(synchronize_session=False)
        )
        session.commit()
        return int(result.rowcount or 0)


@celery_app.task(name="task.quota.reset_daily", ignore_result=True)
def reset_daily_quotas() -> int:
    """Celery 入口：日重置。"""

    return reset_daily_quotas_sync()


@celery_app.task(name="task.quota.reset_monthly", ignore_result=True)
def reset_monthly_quotas() -> int:
    """Celery 入口：月重置。"""

    return reset_monthly_quotas_sync()


__all__ = [
    "reset_daily_quotas",
    "reset_daily_quotas_sync",
    "reset_monthly_quotas",
    "reset_monthly_quotas_sync",
]
