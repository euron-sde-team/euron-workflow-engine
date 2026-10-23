"""`event.emit`: publish an event on this workspace's bus, starting subscribed workflows.

The event is published in the same transaction that records this step's result, so a step
that is retried after a crash does not publish twice.
"""

from __future__ import annotations

import re
from typing import Any

from workflow_engine.nodes.base import (
    NodeConfig,
    NodeContext,
    NodeError,
    NodeResult,
    NodeType,
    templated,
)

EVENT_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,118}[a-z0-9]$")


class EmitConfig(NodeConfig):
    event: str = templated(
        ..., min_length=2, max_length=120, description="For example invoice.created"
    )
    payload: Any = templated(default_factory=dict, widget="json")


async def emit(ctx: NodeContext, config: EmitConfig) -> NodeResult:
    if not EVENT_NAME.match(config.event):
        raise NodeError(
            "invalid_event_name",
            f"'{config.event}' is not a valid event name (lowercase, digits, . _ -).",
        )
    if config.event.startswith("execution."):
        raise NodeError("reserved_event_name", "execution.* events are published by the engine.")
    ctx.log("info", f"Publishing {config.event}")
    return NodeResult(output={"event": config.event}, events=[(config.event, config.payload)])


NODES = [
    NodeType(
        type="event.emit",
        name="Publish event",
        category="core",
        description="Publish an event on the workspace's event bus to start other workflows.",
        icon="send",
        config_model=EmitConfig,
        run=emit,
        default_timeout_s=10,
        side_effects=True,
        sample_output={"event": "invoice.created", "event_id": "", "matched": 1},
    )
]
