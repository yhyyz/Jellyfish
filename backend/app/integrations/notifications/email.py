"""Email 异步发送 integration（W26-T1）。

为什么存在：
    合规 BLOCKER 告警的双通道之一。选用 ``aiosmtplib`` 而非
    ``smtplib`` + threadpool：

    - 纯 async，不阻塞 dispatcher 的 ``asyncio.gather`` 并发；
    - API 与 stdlib ``smtplib`` 极相似，迁移成本低；
    - 支持 STARTTLS / TLS / 认证，覆盖常见 SMTP 服务商。

边界：
    - 本模块只负责"把一封 :class:`email.message.EmailMessage` 用 SMTP
      发出去"；
    - **不**做模板渲染（dispatcher 调 :func:`build_compliance_email_body`
      构造）；
    - **不**做重试（dispatcher 兜底）。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Iterable

import aiosmtplib


logger = logging.getLogger(__name__)


DEFAULT_REQUEST_TIMEOUT_SEC: float = 4.0


class EmailDeliveryError(RuntimeError):
    """SMTP 发送失败时抛出，包装底层 transport 异常。"""


@dataclass(frozen=True)
class SmtpConfig:
    """SMTP 服务器连接配置。

    字段：
        host / port: SMTP server 地址。
        username / password: 可选凭据；同时为 ``None`` 时跳过认证（适合
            本地 ``aiosmtpd`` 测试服务器）。
        use_tls: 直连 TLS（端口通常 465）；与 ``start_tls`` 互斥。
        start_tls: 明文连接后协商 STARTTLS（端口通常 587）。
        sender: ``From`` 字段；不显式传入时 dispatcher 会用 ``username``
            兜底。
    """

    host: str
    port: int
    username: str | None = None
    password: str | None = None
    use_tls: bool = False
    start_tls: bool = False
    sender: str | None = None


def build_compliance_email_body(
    *,
    finding_id: int | str | None,
    severity: str,
    rule_id: str,
    rule_kind: str,
    description: str,
    variant_id: str | None = None,
    location: str | None = None,
    suggested_fix: str | None = None,
) -> str:
    """构造纯文本邮件正文（与 Slack block 信息对齐）。

    用纯 text/plain 而非 HTML：
        - 邮件客户端兼容性最强；
        - 告警类邮件优先信息密度，不需要排版；
        - 简化测试断言。
    """

    lines = [
        "Compliance BLOCKER alert",
        "",
        f"Severity      : {severity}",
        f"Rule ID       : {rule_id}",
        f"Rule kind     : {rule_kind}",
    ]
    if finding_id is not None:
        lines.append(f"Finding ID    : {finding_id}")
    if variant_id:
        lines.append(f"Variant ID    : {variant_id}")
    if location:
        lines.append(f"Location      : {location}")
    lines.extend(["", "Description:", description])
    if suggested_fix:
        lines.extend(["", "Suggested fix:", suggested_fix])
    lines.append("")
    return "\n".join(lines)


async def send_email(
    *,
    config: SmtpConfig,
    sender: str,
    recipients: Iterable[str],
    subject: str,
    body: str,
    timeout_sec: float = DEFAULT_REQUEST_TIMEOUT_SEC,
) -> None:
    """通过 SMTP 异步发送一封纯文本邮件。

    Args:
        config: 连接参数（host/port/认证/TLS）。
        sender: ``From`` 头；通常等于 ``config.username``。
        recipients: 收件人列表，至少 1 个。
        subject: 邮件主题。
        body: 纯文本正文。
        timeout_sec: 整体硬超时（连接 + 鉴权 + 发送），由
            :func:`asyncio.wait_for` 统一兜底。

    Raises:
        EmailDeliveryError: 任何 transport / 鉴权 / 超时错误。
    """

    recipient_list = [r for r in recipients if r]
    if not recipient_list:
        raise EmailDeliveryError("no recipients provided")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = ", ".join(recipient_list)
    message["Subject"] = subject
    message.set_content(body)

    async def _do_send() -> None:
        await aiosmtplib.send(
            message,
            hostname=config.host,
            port=config.port,
            username=config.username,
            password=config.password,
            use_tls=config.use_tls,
            start_tls=config.start_tls if not config.use_tls else False,
        )

    try:
        await asyncio.wait_for(_do_send(), timeout=timeout_sec)
    except asyncio.TimeoutError as exc:
        raise EmailDeliveryError(
            f"smtp send timed out after {timeout_sec}s"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise EmailDeliveryError(f"smtp transport error: {exc}") from exc

    logger.debug(
        "email delivered",
        extra={
            "host": config.host,
            "port": config.port,
            "recipients": recipient_list,
        },
    )


__all__ = [
    "DEFAULT_REQUEST_TIMEOUT_SEC",
    "EmailDeliveryError",
    "SmtpConfig",
    "build_compliance_email_body",
    "send_email",
]
