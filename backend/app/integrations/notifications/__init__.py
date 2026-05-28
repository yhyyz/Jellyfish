"""通知渠道 integration 子包（W26-T1）。

包含两个 async 客户端，统一接口形如：

    async def send(target: str, payload: dict) -> None

成功路径直接 return；失败路径 raise 异常（由 dispatcher 统一捕获 + 重试）。

- :mod:`slack`：基于 ``slack-sdk`` AsyncWebhookClient + block-kit；
- :mod:`email`：基于 ``aiosmtplib`` 的轻量异步 SMTP 发送。
"""

from app.integrations.notifications.slack import (
    SlackDeliveryError,
    build_compliance_blocks,
    send_slack_webhook,
)
from app.integrations.notifications.email import (
    EmailDeliveryError,
    SmtpConfig,
    build_compliance_email_body,
    send_email,
)

__all__ = [
    "SlackDeliveryError",
    "EmailDeliveryError",
    "SmtpConfig",
    "build_compliance_blocks",
    "build_compliance_email_body",
    "send_slack_webhook",
    "send_email",
]
