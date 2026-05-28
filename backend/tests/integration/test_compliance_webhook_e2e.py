"""端到端 webhook smoke：commit → Slack/email 真投递 ≤5s（W26-T1）。

验证 sub-5s SLA：
    - 用 :mod:`aiohttp` 起一个本地 HTTP server 模拟 Slack webhook；
    - 用 :mod:`aiosmtpd` 起一个本地 SMTP server 接收邮件；
    - 在 in-memory SQLite 上落两个 NotificationChannel 行；
    - 触发 dispatcher，记录 wall-clock 耗时；
    - 断言两边都收到 1 条消息，且端到端 ≤ 5s。

只用纯 stdlib + 已 pinned 依赖，避免引入 pytest-aiohttp 等额外测试库。
"""

from __future__ import annotations

import asyncio
import socket
import time
from email import message_from_bytes
from email.message import Message
from typing import Any

import pytest
from aiohttp import web
from aiosmtpd.controller import Controller
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.integrations.notifications.email import SmtpConfig
from app.models.notification_channel import NotificationChannel, NotificationDelivery
from app.services.notifications.compliance_dispatcher import (
    BlockerFindingPayload,
    dispatch_blocker_finding,
)


# ---------------------------------------------------------------------------
# 本地 Slack mock：aiohttp 单端点 server
# ---------------------------------------------------------------------------


class _SlackMockServer:
    """监听 127.0.0.1:0，把所有 POST 的 JSON 存到 ``self.received``。"""

    def __init__(self) -> None:
        self.received: list[dict[str, Any]] = []
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self.url: str = ""

    async def start(self) -> None:
        async def handler(request: web.Request) -> web.Response:
            self.received.append(await request.json())
            return web.Response(text="ok", status=200)

        app = web.Application()
        app.router.add_post("/slack", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        self._runner = runner
        self._site = site
        self.url = f"http://127.0.0.1:{port}/slack"

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()


class _SmtpCapture:
    def __init__(self) -> None:
        self.messages: list[Message] = []

    async def handle_DATA(self, server, session, envelope):  # type: ignore[no-untyped-def]
        self.messages.append(message_from_bytes(envelope.content))
        return "250 OK"


@pytest.mark.asyncio
async def test_e2e_slack_email_dispatch_sub_5s() -> None:
    # 1. 起 mock Slack server
    slack_mock = _SlackMockServer()
    await slack_mock.start()

    # 2. 起 aiosmtpd（aiosmtpd Controller 不支持 port=0 自选）
    smtp_handler = _SmtpCapture()
    smtp_sock = socket.socket()
    smtp_sock.bind(("127.0.0.1", 0))
    smtp_port = smtp_sock.getsockname()[1]
    smtp_sock.close()
    smtp_controller = Controller(smtp_handler, hostname="127.0.0.1", port=smtp_port)
    smtp_controller.start()

    # 3. 起 in-memory SQLite + 落两个渠道
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: NotificationChannel.__table__.create(c, checkfirst=True)
        )
        await conn.run_sync(
            lambda c: NotificationDelivery.__table__.create(c, checkfirst=True)
        )
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    try:
        async with maker() as session:
            session.add_all(
                [
                    NotificationChannel(
                        id="slack-e2e",
                        profile_id=None,
                        kind="slack",
                        target=slack_mock.url,
                        enabled=True,
                    ),
                    NotificationChannel(
                        id="email-e2e",
                        profile_id=None,
                        kind="email",
                        target="legal@example.com",
                        enabled=True,
                    ),
                ]
            )
            await session.commit()

            smtp_config = SmtpConfig(
                host=smtp_controller.hostname,
                port=smtp_controller.port,
                username=None,
                password=None,
                use_tls=False,
                start_tls=False,
            )

            payload = BlockerFindingPayload(
                finding_id=1,
                severity="blocker",
                rule_id="cn_no_health_claim",
                rule_kind="banned_phrase",
                description="包含夸大功效",
                variant_id="v1",
            )

            t0 = time.monotonic()
            result = await dispatch_blocker_finding(
                payload,
                session=session,
                smtp_config=smtp_config,
                smtp_sender="alerts@example.com",
            )
            elapsed = time.monotonic() - t0

            assert result.succeeded == 2, f"result={result}"
            assert result.failed == 0
            assert elapsed <= 5.0, f"e2e elapsed {elapsed:.2f}s > 5s SLA"
            assert len(slack_mock.received) == 1
            slack_payload = slack_mock.received[0]
            assert "cn_no_health_claim" in slack_payload["text"]
            assert any(
                b["type"] == "header" for b in slack_payload.get("blocks", [])
            )

            assert len(smtp_handler.messages) == 1
            msg = smtp_handler.messages[0]
            assert msg["From"] == "alerts@example.com"
            assert msg["To"] == "legal@example.com"
            assert "Compliance BLOCKER" in (msg["Subject"] or "")
    finally:
        smtp_controller.stop()
        await slack_mock.stop()
        await engine.dispose()
