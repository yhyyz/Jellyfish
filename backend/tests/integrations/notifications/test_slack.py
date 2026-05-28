"""Slack integration 单元测试（W26-T1）。

覆盖：
    - block-kit 构造：包含 severity / rule_id / description / 可选字段；
    - send_slack_webhook 成功路径：mock AsyncWebhookClient 验证 payload；
    - send_slack_webhook 失败路径：4xx / 5xx / 超时 / transport 异常。
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.integrations.notifications.slack import (
    SlackDeliveryError,
    build_compliance_blocks,
    send_slack_webhook,
)


def test_build_compliance_blocks_minimal() -> None:
    blocks = build_compliance_blocks(
        finding_id=42,
        severity="blocker",
        rule_id="cn_no_health_claim",
        rule_kind="banned_phrase",
        description="包含夸大功效",
    )
    assert blocks[0]["type"] == "header"
    assert blocks[0]["text"]["text"] == "合规 BLOCKER 告警"

    section = blocks[1]
    assert section["type"] == "section"
    field_texts = [f["text"] for f in section["fields"]]
    assert any("blocker" in t for t in field_texts)
    assert any("cn_no_health_claim" in t for t in field_texts)
    assert any("banned_phrase" in t for t in field_texts)
    assert any("`42`" in t for t in field_texts)

    desc_block = blocks[2]
    assert "包含夸大功效" in desc_block["text"]["text"]


def test_build_compliance_blocks_with_optionals() -> None:
    blocks = build_compliance_blocks(
        finding_id="f-9",
        severity="blocker",
        rule_id="r1",
        rule_kind="banned_phrase",
        description="d",
        variant_id="v1",
        location="char_offset:12",
        suggested_fix="改写为温和表达",
    )
    flat = str(blocks)
    assert "v1" in flat
    assert "char_offset:12" in flat
    assert "改写为温和表达" in flat
    assert blocks[-1]["text"]["text"].startswith("*Suggested fix*")


class _FakeResponse:
    def __init__(self, status_code: int = 200, body: str = "ok"):
        self.status_code = status_code
        self.body = body


@pytest.mark.asyncio
async def test_send_slack_webhook_success() -> None:
    captured: dict[str, Any] = {}

    async def fake_send_dict(self, payload):  # type: ignore[no-untyped-def]
        captured["payload"] = payload
        captured["url"] = self.url
        return _FakeResponse(200)

    with patch(
        "app.integrations.notifications.slack.AsyncWebhookClient.send_dict",
        new=fake_send_dict,
    ):
        await send_slack_webhook(
            "https://hooks.slack.com/services/AAA/BBB",
            text="hi",
            blocks=[{"type": "header", "text": {"type": "plain_text", "text": "x"}}],
        )

    assert captured["url"] == "https://hooks.slack.com/services/AAA/BBB"
    assert captured["payload"]["text"] == "hi"
    assert captured["payload"]["blocks"][0]["type"] == "header"


@pytest.mark.asyncio
async def test_send_slack_webhook_4xx_raises() -> None:
    async def fake_send_dict(self, payload):  # type: ignore[no-untyped-def]
        return _FakeResponse(400, "invalid_payload")

    with patch(
        "app.integrations.notifications.slack.AsyncWebhookClient.send_dict",
        new=fake_send_dict,
    ):
        with pytest.raises(SlackDeliveryError) as ei:
            await send_slack_webhook("https://x", text="hi")
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_send_slack_webhook_timeout_raises() -> None:
    async def fake_send_dict(self, payload):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0.5)
        return _FakeResponse(200)

    with patch(
        "app.integrations.notifications.slack.AsyncWebhookClient.send_dict",
        new=fake_send_dict,
    ):
        with pytest.raises(SlackDeliveryError) as ei:
            await send_slack_webhook("https://x", text="hi", timeout_sec=0.05)
    assert "timed out" in str(ei.value)


@pytest.mark.asyncio
async def test_send_slack_webhook_transport_error_raises() -> None:
    async def fake_send_dict(self, payload):  # type: ignore[no-untyped-def]
        raise RuntimeError("conn refused")

    with patch(
        "app.integrations.notifications.slack.AsyncWebhookClient.send_dict",
        new=fake_send_dict,
    ):
        with pytest.raises(SlackDeliveryError) as ei:
            await send_slack_webhook("https://x", text="hi")
    assert "transport" in str(ei.value)
