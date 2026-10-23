from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from workflow_engine.schemas.common import ApiModel


class RetryOut(ApiModel):
    max_attempts: int
    initial_delay_ms: int
    max_delay_ms: int
    multiplier: float
    jitter: bool


class NodeTypeOut(ApiModel):
    type: str
    name: str
    category: str
    description: str
    icon: str
    is_trigger: bool
    inputs: list[str]
    ports: list[str]
    port_labels: dict[str, str]
    dynamic_ports: bool
    side_effects: bool
    default_retry: RetryOut
    default_timeout_s: int
    template_fields: list[str]
    credential_fields: dict[str, list[str]]
    config_schema: dict[str, Any]
    sample_output: Any = None


class TemplateSummaryOut(ApiModel):
    slug: str
    name: str
    summary: str
    description: str
    category: str
    tags: list[str]
    node_types: list[str]
    trigger_kinds: list[str]
    credentials: list[dict[str, str]]
    variables: list[dict[str, str]]


class TemplateOut(TemplateSummaryOut):
    definition: dict[str, Any]


class CronPreviewRequest(ApiModel):
    expression: str = Field(min_length=1, max_length=120)
    timezone: str = Field(default="UTC", max_length=64)
    count: int = Field(default=5, ge=1, le=20)


class CronPreviewOut(ApiModel):
    valid: bool
    description: str | None = None
    next: list[datetime] = Field(default_factory=list)
    error: str | None = None
