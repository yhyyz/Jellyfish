"""API key 配额相关 ORM 模型。

设计说明：
- 这张表用于 P3 阶段的 partner / 外部 API key 配额管理；
- P1 阶段仅 *建表预留*，不暴露读写接口，也不挂业务逻辑；
- 主键直接采用 ``api_key_hash``（API key 的 bcrypt 哈希），
  以便在不持久化明文 key 的前提下唯一标识一条配额记录；
- 实际的哈希/校验发生在认证层，本模型只负责存储字段。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Boolean, Date, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin


class ApiKeyQuota(Base, TimestampMixin):
    """每个 API key 的配额记录 — P3 启用 partner API 时使用，P1 仅建表预留。"""

    __tablename__ = "api_key_quotas"

    api_key_hash: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
        comment="API key 的 bcrypt 哈希（PK）",
    )
    daily_limit: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1000,
        server_default="1000",
        comment="日调用上限",
    )
    monthly_limit: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=30000,
        server_default="30000",
        comment="月调用上限",
    )
    rate_per_minute: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=60,
        server_default="60",
        comment="每分钟请求数上限",
    )
    consumed_today: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="今日已消耗",
    )
    consumed_this_month: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="本月已消耗",
    )
    last_reset_daily: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="上次日重置日期",
    )
    last_reset_monthly: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="上次月重置日期",
    )
    description: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
        server_default="",
        comment="key 用途备注",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
        index=True,
        comment="是否启用",
    )


__all__ = ["ApiKeyQuota"]
