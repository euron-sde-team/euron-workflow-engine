"""`slack.message`: post to a Slack incoming webhook, or any Slack-compatible receiver."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import orjson
from pydantic import Field

from workflow_engine.engine.definition import RetryPolicy
from workflow_engine.integrations.http import OutboundBlockedError
from workflow_engine.nodes.base import (
    NodeConfig,
    NodeContext,
    NodeError,
    NodeResult,
    NodeType,
    credential,
    templated,
)

SLACK_CREDENTIALS = frozenset({"slack_webhook"})


class SlackConfig(NodeConfig):
    credential_id: uuid.UUID = credential("slack_webhook", required=True)
    text: str = templated(..., widget="textarea", min_length=1, max_length=4000)
    blocks: Any = templated(None, widget="json", description="Optional Block Kit blocks.")
    username: str | None = Field(default=None, max_length=80)
    icon_emoji: str | None = Field(default=None, pattern=r"^:[a-z0-9_+-]+:$")


async def post(ctx: NodeContext, config: SlackConfig) -> NodeResult:
    resolved = await ctx.credential(config.credential_id, SLACK_CREDENTIALS)
    url = str(resolved.values["url"])
    payload: dict[str, Any] = {"text": config.text}
    if config.blocks:
        if not isinstance(config.blocks, list):
            raise NodeError("invalid_blocks", "blocks must be a list of Block Kit blocks.")
        payload["blocks"] = config.blocks
    if config.username:
        payload["username"] = config.username
    if config.icon_emoji:
        payload["icon_emoji"] = config.icon_emoji
    try:
        response = await ctx.services.http.post(
            url,
            content=orjson.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
    except OutboundBlockedError as exc:
        raise NodeError("blocked_address", str(exc)) from exc
    except httpx.TimeoutException as exc:
        raise NodeError("timeout", "Slack did not answer in 15 s.", retryable=True) from exc
    except httpx.TransportError as exc:
        raise NodeError("network_error", f"Slack is not reachable: {exc}", retryable=True) from exc
    text = response.text[:300]
    if response.status_code >= 400:
        retryable = response.status_code == 429 or response.status_code >= 500
        raise NodeError(
            f"slack_{response.status_code}",
            f"Slack answered {response.status_code}: {text}",
            retryable=retryable,
        )
    ctx.log("info", f"Posted to Slack ({response.status_code})", characters=len(config.text))
    return NodeResult(output={"status": response.status_code, "response": text})


NODES = [
    NodeType(
        type="slack.message",
        name="Slack message",
        category="integration",
        description="Post a message to a Slack incoming webhook (or any compatible receiver).",
        icon="message-square",
        config_model=SlackConfig,
        run=post,
        default_retry=RetryPolicy(max_attempts=3, initial_delay_ms=1000, max_delay_ms=30_000),
        default_timeout_s=20,
        side_effects=True,
        sample_output={"status": 200, "response": "ok"},
    )
]
