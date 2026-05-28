"""通知子系统 service 层包（W26-T1）。

包含：
    - :mod:`compliance_dispatcher`：合规 BLOCKER finding 的 fan-out
      dispatcher（Slack + email 双通道，3 次指数退避重试）；
    - :mod:`delivery_log`：失败投递落库助手。
"""

from app.services.notifications.compliance_dispatcher import (
    BlockerFindingPayload,
    DispatcherResult,
    dispatch_blocker_finding,
    dispatch_blocker_findings,
)
from app.services.notifications.delivery_log import record_failed_delivery

__all__ = [
    "BlockerFindingPayload",
    "DispatcherResult",
    "dispatch_blocker_finding",
    "dispatch_blocker_findings",
    "record_failed_delivery",
]
