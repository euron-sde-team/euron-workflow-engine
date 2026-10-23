from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from workflow_engine.schemas.common import ApiModel


class NodeTestRequest(ApiModel):
    node: dict[str, Any] = Field(description="The node as in a definition: id, type, name, config.")
    input: Any = None
    trigger: Any = None
    steps: dict[str, Any] = Field(default_factory=dict)
    vars: dict[str, Any] = Field(default_factory=dict)


class LogLineOut(ApiModel):
    level: str
    message: str
    data: dict[str, Any]


class NodeTestResult(ApiModel):
    status: Literal["succeeded", "failed"]
    output: Any = None
    ports: list[str] = Field(default_factory=list)
    vars: dict[str, Any] | None = None
    events: list[dict[str, Any]] = Field(
        default_factory=list, description="Events the node would publish; test runs publish none."
    )
    suspend_until: str | None = None
    logs: list[LogLineOut] = Field(default_factory=list)
    error: dict[str, Any] | None = None
    duration_ms: int
