"""Slack 异步 webhook integration（W26-T1）。

为什么存在：
    P4 要求合规 BLOCKER finding 落地后立即 fan-out 到 Slack/email 渠道，
    p95 ≤5s 端到端。Slack 路径选用官方 ``slack-sdk`` 的
    :class:`AsyncWebhookClient`：

    - 内置 block-kit 数据结构与 Webhook 鉴权细节，避免我们手搓 JSON；
    - 默认走 aiohttp，纯 async，重试/超时可在 dispatcher 层统一管控；
    - block-kit 比 plain text 更适合"严重告警"场景（粗体、按钮、字段
      分组）。

边界：
    - 本模块**不**做重试：retry/backoff 由 dispatcher 统一编排，避免每个
      integration 各自实现一套；
    - 本模块**不**做 channel 启用判断：dispatcher 已过滤 ``enabled=True``；
    - 本模块只面向 webhook URL 模式（incoming-webhook），不做 OAuth Bot。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Mapping

from slack_sdk.webhook.async_client import AsyncWebhookClient


logger = logging.getLogger(__name__)


# 单次 HTTP 调用的硬超时（秒）；dispatcher 还有"3 次重试 + 指数退避"
# 的上层兜底。这里默认 3s 给端到端 5s SLA 留足空间。
DEFAULT_REQUEST_TIMEOUT_SEC: float = 3.0


class SlackDeliveryError(RuntimeError):
    """Slack webhook 投递失败时抛出，统一带上 status_code / body。"""

    def __init__(self, message: str, *, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def build_compliance_blocks(
    *,
    finding_id: int | str | None,
    severity: str,
    rule_id: str,
    rule_kind: str,
    description: str,
    variant_id: str | None = None,
    location: str | None = None,
    suggested_fix: str | None = None,
    title: str = "合规 BLOCKER 告警",
) -> list[dict[str, Any]]:
    """构造 Slack block-kit blocks 数组。

    设计上把 finding 的关键信息压成 4 个 block：

        1. ``header`` —— 醒目标题；
        2. ``section`` 含若干 fields —— 严重度 / 规则 ID / kind / variant；
        3. ``section`` —— 问题描述（mrkdwn）；
        4. ``section`` —— 建议修复（仅在有内容时追加）。

    返回值是裸 ``list[dict]``，方便 :func:`send_slack_webhook` 透传给
    AsyncWebhookClient，也便于测试用 ``json.dumps`` 比较。
    """

    fields: list[dict[str, str]] = [
        {"type": "mrkdwn", "text": f"*Severity*\n{severity}"},
        {"type": "mrkdwn", "text": f"*Rule*\n`{rule_id}`"},
        {"type": "mrkdwn", "text": f"*Kind*\n{rule_kind}"},
    ]
    if variant_id:
        fields.append({"type": "mrkdwn", "text": f"*Variant*\n`{variant_id}`"})
    if finding_id is not None:
        fields.append({"type": "mrkdwn", "text": f"*Finding*\n`{finding_id}`"})
    if location:
        fields.append({"type": "mrkdwn", "text": f"*Location*\n{location}"})

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": title, "emoji": True},
        },
        {"type": "section", "fields": fields},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Description*\n{description}",
            },
        },
    ]
    if suggested_fix:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Suggested fix*\n{suggested_fix}",
                },
            }
        )
    return blocks


async def send_slack_webhook(
    webhook_url: str,
    *,
    text: str,
    blocks: list[dict[str, Any]] | None = None,
    timeout_sec: float = DEFAULT_REQUEST_TIMEOUT_SEC,
    extra_payload: Mapping[str, Any] | None = None,
) -> None:
    """向 Slack incoming-webhook 投递一条告警。

    Args:
        webhook_url: Slack webhook URL（``https://hooks.slack.com/services/...``）。
        text: 兜底文本（通知 banner、邮件回退用）。Slack 要求 webhook
            必须带 text，即便 blocks 已含信息。
        blocks: 可选 block-kit 数组；若提供，UI 优先按 blocks 渲染。
        timeout_sec: 单次 HTTP 请求超时。
        extra_payload: 可选附加字段（``username`` / ``icon_emoji`` 等）。

    Raises:
        SlackDeliveryError: HTTP 失败、Slack 返回非 200 或解析异常。
    """

    payload: dict[str, Any] = {"text": text}
    if blocks is not None:
        payload["blocks"] = blocks
    if extra_payload:
        payload.update(extra_payload)

    client = AsyncWebhookClient(webhook_url)
    try:
        response = await asyncio.wait_for(
            client.send_dict(payload),
            timeout=timeout_sec,
        )
    except asyncio.TimeoutError as exc:
        raise SlackDeliveryError(
            f"slack webhook timed out after {timeout_sec}s"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise SlackDeliveryError(f"slack webhook transport error: {exc}") from exc

    status_code = getattr(response, "status_code", None)
    body = getattr(response, "body", None)
    if status_code is None or status_code >= 400:
        raise SlackDeliveryError(
            f"slack webhook non-2xx: status={status_code}",
            status_code=status_code,
            body=body if isinstance(body, str) else None,
        )
    logger.debug(
        "slack webhook delivered",
        extra={"status_code": status_code, "body": body},
    )


__all__ = [
    "DEFAULT_REQUEST_TIMEOUT_SEC",
    "SlackDeliveryError",
    "build_compliance_blocks",
    "send_slack_webhook",
]
