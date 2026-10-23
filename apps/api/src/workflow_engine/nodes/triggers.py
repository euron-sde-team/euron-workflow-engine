"""Trigger nodes: they start executions and never run as steps.

Their configuration is what the trigger index (`workflow_triggers`), the webhook ingress,
the scheduler and the event bus read. The step recorded for a trigger holds the payload it
started with, which templates read as `trigger`.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from workflow_engine.engine import cron
from workflow_engine.engine.expressions import ExpressionError, compile_expression
from workflow_engine.nodes.base import NodeConfig, NodeType, credential, widget

WEBHOOK_PATH = r"^[a-z0-9][a-z0-9/_-]{0,99}$"
EVENT_NAME = r"^[a-z0-9][a-z0-9_.-]{0,118}[a-z0-9*]$"
MIN_INTERVAL = timedelta(seconds=10)
MAX_INTERVAL = timedelta(days=30)
_UNITS = {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400}


class ManualTriggerConfig(NodeConfig):
    sample_payload: Any = widget(
        default_factory=dict,
        name="json",
        description="Used when the workflow is run from the editor without a payload.",
    )


class WebhookTriggerConfig(NodeConfig):
    path: str = Field(
        pattern=WEBHOOK_PATH,
        description="Called at /hooks/<workspace>/<path>. Lowercase letters, digits, - _ /.",
    )
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "POST"
    auth: Literal["none", "hmac_sha256", "bearer"] = Field(
        default="hmac_sha256",
        description="hmac_sha256 verifies a signature over the raw body; bearer a shared token.",
    )
    credential_id: uuid.UUID | None = credential(
        "webhook_secret", description="The signing secret or token (a webhook secret)."
    )
    signature_header: str = Field(default="X-Signature", min_length=1, max_length=80)
    signature_prefix: str = Field(default="sha256=", max_length=20)
    timestamp_header: str | None = Field(
        default=None,
        max_length=80,
        description="When set, the signature covers '<timestamp>.<body>'; old requests fail.",
    )
    tolerance_s: int = Field(default=300, ge=30, le=3600)
    token_header: str = Field(default="Authorization", min_length=1, max_length=80)
    idempotency_header: str = Field(default="Idempotency-Key", min_length=1, max_length=80)
    response: Literal["accepted", "when_finished"] = Field(
        default="accepted",
        description="accepted answers 202 at once; when_finished waits for the output.",
    )
    response_timeout_s: int = Field(default=20, ge=1, le=25)
    sample_payload: Any = widget(default_factory=dict, name="json")

    @model_validator(mode="after")
    def _secret_required(self) -> WebhookTriggerConfig:
        if self.auth != "none" and not self.credential_id:
            raise ValueError("Choose the webhook secret that signs or authorizes requests.")
        if self.path.endswith("/") or "//" in self.path:
            raise ValueError("The path cannot end with '/' or contain '//'.")
        return self


class CronTriggerConfig(NodeConfig):
    expression: str = widget(name="cron", min_length=1, max_length=120)
    timezone: str = widget("UTC", name="timezone", max_length=64)
    overlap: Literal["allow", "skip"] = Field(
        default="allow",
        description="skip: do not start while an earlier execution is still queued or running.",
    )

    @model_validator(mode="after")
    def _parse(self) -> CronTriggerConfig:
        try:
            cron.parse(self.expression, self.timezone)
        except cron.CronError as exc:
            raise ValueError(str(exc)) from exc
        return self


class IntervalTriggerConfig(NodeConfig):
    every: int = Field(default=5, ge=1, le=100_000)
    unit: Literal["seconds", "minutes", "hours", "days"] = "minutes"
    overlap: Literal["allow", "skip"] = "allow"

    @property
    def seconds(self) -> int:
        return self.every * _UNITS[self.unit]

    @model_validator(mode="after")
    def _bounds(self) -> IntervalTriggerConfig:
        span = timedelta(seconds=self.seconds)
        if span < MIN_INTERVAL or span > MAX_INTERVAL:
            raise ValueError("The interval must be between 10 seconds and 30 days.")
        return self


class EventTriggerConfig(NodeConfig):
    event: str = Field(
        pattern=EVENT_NAME,
        description="An event name such as order.created, or a prefix such as order.*",
    )
    filter: str | None = widget(
        None,
        name="expression",
        max_length=2000,
        description="Optional JMESPath over the payload; the workflow starts only when true.",
    )
    sample_payload: Any = widget(default_factory=dict, name="json")

    @field_validator("event")
    @classmethod
    def _wildcard_only_at_the_end(cls, value: str) -> str:
        if "*" in value[:-1] or (value.endswith("*") and not value.endswith(".*")):
            raise ValueError("Use '*' only as a final segment, as in order.*")
        return value

    @field_validator("filter")
    @classmethod
    def _compiles(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        try:
            compile_expression(value)
        except ExpressionError as exc:
            raise ValueError(str(exc)) from exc
        return value


def event_matches(pattern: str, name: str) -> bool:
    if pattern.endswith(".*"):
        return name.startswith(pattern[:-1])
    return pattern == name


NODES = [
    NodeType(
        type="trigger.manual",
        name="Manual trigger",
        category="trigger",
        description="Run the workflow from the editor, the API or another tool.",
        icon="play",
        config_model=ManualTriggerConfig,
        is_trigger=True,
        inputs=(),
    ),
    NodeType(
        type="trigger.webhook",
        name="Webhook",
        category="trigger",
        description="Start on an HTTP request, verified by signature, deduplicated by key.",
        icon="webhook",
        config_model=WebhookTriggerConfig,
        is_trigger=True,
        inputs=(),
        sample_output={"method": "POST", "path": "orders", "headers": {}, "query": {}, "body": {}},
    ),
    NodeType(
        type="trigger.cron",
        name="Schedule",
        category="trigger",
        description="Start on a cron schedule in any time zone.",
        icon="calendar-clock",
        config_model=CronTriggerConfig,
        is_trigger=True,
        inputs=(),
        sample_output={"scheduled_for": "2026-10-23T08:00:00Z", "fired_at": "2026-10-23T08:00:00Z"},
    ),
    NodeType(
        type="trigger.interval",
        name="Interval",
        category="trigger",
        description="Start every N seconds, minutes, hours or days.",
        icon="timer",
        config_model=IntervalTriggerConfig,
        is_trigger=True,
        inputs=(),
        sample_output={"scheduled_for": "2026-10-23T08:00:00Z", "fired_at": "2026-10-23T08:00:00Z"},
    ),
    NodeType(
        type="trigger.event",
        name="Event",
        category="trigger",
        description="Start when an event is published on this workspace's event bus.",
        icon="radio-tower",
        config_model=EventTriggerConfig,
        is_trigger=True,
        inputs=(),
        sample_output={"event": "order.created", "payload": {}, "event_id": "", "source": "api"},
    ),
]
