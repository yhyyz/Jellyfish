"""团队级 BLOCKER 升级状态 ORM（W26-T2）。

为什么存在：
    W26-T1 dispatcher 已实现 BLOCKER finding 在 Slack/email 渠道上的 fan-out。
    但当**同一个团队/profile 在短窗口内连续触发多次 BLOCKER** 时，仅靠普通
    渠道的 fan-out 无法把信号"放大"到对应的负责人（owner），运维/法务侧难
    以识别"反复违规"的高危场景。

    本表给 escalation engine 做"滑动窗口 + 连续计数器"的轻量持久化：

    - ``profile_id`` / ``team_id``：升级状态的归属维度。当前 P4 没有 User /
      Team 表，因此 ``team_id`` 留 nullable 作前向兼容；实际归属由
      ``profile_id`` 主导，且采用稳定字符串 PK ``id`` 作为 upsert key
      （形如 ``profile:{profile_id}`` 或 ``__global__``）。
    - ``consecutive_blockers``：当前窗口内已经累计的 BLOCKER 次数。
    - ``window_start_at``：当前窗口的起始时间（首次触发时落地，窗口超时后
      被覆盖重置）。
    - ``last_escalated_at``：最近一次"已上升通知 owner"的时间，仅做审计/
      去抖参考；逻辑上不依赖此字段做下次判断。

边界：
    - 本模块不实现策略逻辑（计数 / 窗口判定 / owner 通知），策略统一放在
      :mod:`app.services.notifications.escalation_engine`；
    - 本模块不引入 RBAC / User 表 —— owner 的解析走环境变量
      ``ESCALATION_OWNER_EMAIL``（见 :class:`app.config.Settings`），不依赖
      用户系统；
    - 本表只承载"升级触发器状态"，不存储 finding 历史快照，避免与
      :class:`ComplianceFinding` 重复。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin


class EscalationState(Base, TimestampMixin):
    """BLOCKER 升级状态计数器（W26-T2）。

    主键 ``id`` 为稳定字符串，便于 escalation engine 做 SELECT-or-INSERT
    upsert。建议构造规则（由 service 层封装，不在 ORM 层硬编码）：

        - 关联到 profile：``f"profile:{profile_id}"``
        - 全局兜底：``"__global__"``

    字段语义：
        consecutive_blockers: 当前窗口内累计 BLOCKER 数量；触发升级后由
            engine 重置为 0，下次 BLOCKER 进来时再从 1 开始计数。
        window_start_at: 当前窗口的起始时间。窗口长度由调用方（engine）
            决定，超时后引擎会用新的 BLOCKER 时间覆写此字段。
        last_escalated_at: 最近一次升级触发的时间，仅用于审计 / 监控
            面板；engine 的判定逻辑不依赖此字段。
    """

    __tablename__ = "escalation_state"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        comment="稳定字符串 ID（如 profile:{profile_id} 或 __global__）",
    )
    profile_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("compliance_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="可选关联到合规 profile；profile 被删除时降级为全局口径",
    )
    team_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="预留团队维度（当前 P4 无 Team 表，仅前向兼容）",
    )
    consecutive_blockers: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="当前窗口内已累计的 BLOCKER 次数",
    )
    window_start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="当前计数窗口的起始时间（UTC）",
    )
    last_escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="最近一次升级触发时间（UTC，仅审计参考）",
    )

    __table_args__ = (
        Index(
            "ix_escalation_state_profile_team",
            "profile_id",
            "team_id",
        ),
    )


__all__ = ["EscalationState"]
