"""Email integration 单元测试（W26-T1）。

覆盖：
    - build_compliance_email_body：纯文本格式与字段拼接；
    - send_email：用 aiosmtpd 起本地测试 SMTP server，断言收到的邮件
      头与正文与构造一致；
    - 失败路径：连不上 SMTP 抛 EmailDeliveryError。
"""

from __future__ import annotations

import asyncio
import socket
from email import message_from_bytes
from email.message import Message
from typing import Any

import pytest
from aiosmtpd.controller import Controller

from app.integrations.notifications.email import (
    EmailDeliveryError,
    SmtpConfig,
    build_compliance_email_body,
    send_email,
)


def _free_port() -> int:
    """获取一个空闲端口；aiosmtpd Controller 不支持 port=0 自动选择。"""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _CapturingHandler:
    """aiosmtpd handler：把每封邮件原始字节存到 ``self.messages``。"""

    def __init__(self) -> None:
        self.messages: list[Message] = []
        self.envelopes: list[tuple[str, list[str]]] = []

    async def handle_DATA(self, server: Any, session: Any, envelope: Any) -> str:
        self.messages.append(message_from_bytes(envelope.content))
        self.envelopes.append((envelope.mail_from, list(envelope.rcpt_tos)))
        return "250 OK"


@pytest.fixture
def smtp_server():
    handler = _CapturingHandler()
    controller = Controller(handler, hostname="127.0.0.1", port=_free_port())
    controller.start()
    try:
        yield controller, handler
    finally:
        controller.stop()


def test_build_compliance_email_body_basic() -> None:
    body = build_compliance_email_body(
        finding_id=7,
        severity="blocker",
        rule_id="r1",
        rule_kind="banned_phrase",
        description="dd",
        variant_id="v1",
        location="char_offset:5",
        suggested_fix="改写",
    )
    assert "Compliance BLOCKER alert" in body
    assert "Severity      : blocker" in body
    assert "Rule ID       : r1" in body
    assert "Finding ID    : 7" in body
    assert "Variant ID    : v1" in body
    assert "char_offset:5" in body
    assert "Suggested fix:" in body
    assert "改写" in body


def test_build_compliance_email_body_minimal_no_fix() -> None:
    body = build_compliance_email_body(
        finding_id=None,
        severity="blocker",
        rule_id="r1",
        rule_kind="banned_phrase",
        description="dd",
    )
    assert "Suggested fix" not in body
    assert "Variant ID" not in body
    assert "Finding ID" not in body


@pytest.mark.asyncio
async def test_send_email_via_aiosmtpd(smtp_server) -> None:
    controller, handler = smtp_server
    config = SmtpConfig(
        host=controller.hostname,
        port=controller.port,
        username=None,
        password=None,
        use_tls=False,
        start_tls=False,
    )
    await send_email(
        config=config,
        sender="alerts@example.com",
        recipients=["legal@example.com"],
        subject="hello",
        body="line1\nline2",
        timeout_sec=3.0,
    )

    assert len(handler.messages) == 1
    msg = handler.messages[0]
    assert msg["From"] == "alerts@example.com"
    assert msg["To"] == "legal@example.com"
    assert msg["Subject"] == "hello"
    payload = msg.get_payload()
    if isinstance(payload, list):
        payload = payload[0].get_payload()
    assert "line1" in payload and "line2" in payload
    assert handler.envelopes[0][1] == ["legal@example.com"]


@pytest.mark.asyncio
async def test_send_email_no_recipients_raises() -> None:
    config = SmtpConfig(host="127.0.0.1", port=1, username=None, password=None)
    with pytest.raises(EmailDeliveryError):
        await send_email(
            config=config,
            sender="a@b",
            recipients=[],
            subject="s",
            body="b",
        )


@pytest.mark.asyncio
async def test_send_email_unreachable_smtp_raises() -> None:
    # 用一个几乎可保证关闭的 port（1）触发 transport error
    config = SmtpConfig(host="127.0.0.1", port=1, username=None, password=None)
    with pytest.raises(EmailDeliveryError):
        await send_email(
            config=config,
            sender="a@b",
            recipients=["x@y"],
            subject="s",
            body="b",
            timeout_sec=1.5,
        )
