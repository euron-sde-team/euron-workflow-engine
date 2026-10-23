"""What every node type is made of, and what a node receives and returns when it runs.

A node type is a config model (validation, and the editor's form through its JSON Schema),
its ports, its default retry and timeout, and a `run` coroutine. Field metadata in the JSON
Schema drives the editor:

    x-template          the field accepts {{ }} templates; rendered before run()
    x-widget            how to edit it: json, textarea, code, key-value, cron, timezone, ...
    x-credential-types  a credential picker limited to these credential types
"""

from __future__ import annotations

import builtins
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field
from pydantic_core import PydanticUndefined

from workflow_engine.core.config import Settings
from workflow_engine.engine.definition import NodeSpec, RetryPolicy
from workflow_engine.engine.routing import LoopStart

if TYPE_CHECKING:
    import httpx

    from workflow_engine.integrations.aws import AwsClients
    from workflow_engine.integrations.http import NetworkPolicy

LogLevel = Literal["debug", "info", "warn", "error"]
Category = Literal["trigger", "core", "flow", "integration"]


class NodeConfig(BaseModel):
    """Base for every node config: unknown keys are errors, so typos surface in the editor."""

    model_config = ConfigDict(extra="forbid")


def templated(default: Any = PydanticUndefined, *, widget: str | None = None, **kwargs: Any) -> Any:
    extra: dict[str, Any] = {"x-template": True}
    if widget:
        extra["x-widget"] = widget
    return Field(default, json_schema_extra=extra, **kwargs)


def widget(default: Any = PydanticUndefined, *, name: str, **kwargs: Any) -> Any:
    return Field(default, json_schema_extra={"x-widget": name}, **kwargs)


def credential(*types: str, required: bool = False, **kwargs: Any) -> Any:
    extra: dict[str, Any] = {"x-widget": "credential", "x-credential-types": list(types)}
    if required:
        return Field(json_schema_extra=extra, **kwargs)
    return Field(default=None, json_schema_extra=extra, **kwargs)


class NodeError(Exception):
    """How a node fails. `retryable` decides between a retry and a terminal failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
        retry_after_s: float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}
        self.retry_after_s = retry_after_s

    def to_json(self) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        body["retryable"] = self.retryable
        if self.details:
            body["details"] = self.details
        return body


@dataclass(slots=True)
class NodeResult:
    output: Any = None
    ports: tuple[str, ...] = ("main",)
    vars: dict[str, Any] | None = None
    loop_start: LoopStart | None = None
    suspend_until: datetime | None = None
    events: list[tuple[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ResolvedCredential:
    id: uuid.UUID
    type: str
    values: dict[str, Any]

    def secret_values(self) -> list[str]:
        return [v for v in self.values.values() if isinstance(v, str) and len(v) >= 4]


@dataclass(frozen=True, slots=True)
class LogLine:
    level: LogLevel
    message: str
    data: dict[str, Any]


class NodeServices(Protocol):
    """What a node may use. Built by the worker (or the test-run service) per step."""

    @property
    def settings(self) -> Settings: ...

    @property
    def http(self) -> httpx.AsyncClient: ...

    @property
    def aws(self) -> AwsClients: ...

    @property
    def network_policy(self) -> NetworkPolicy: ...

    async def credential(
        self, workspace_id: uuid.UUID, credential_id: uuid.UUID, accepted: frozenset[str]
    ) -> ResolvedCredential: ...


@dataclass
class NodeContext:
    workspace_id: uuid.UUID
    execution_id: uuid.UUID | None
    step_id: uuid.UUID | None
    node: NodeSpec
    input: Any
    expression_context: dict[str, Any]
    now: datetime
    attempt: int
    services: NodeServices
    resumed: bool = False
    test_run: bool = False
    logs: list[LogLine] = field(default_factory=list)
    secrets: list[str] = field(default_factory=list)

    def log(self, level: LogLevel, message: str, **data: Any) -> None:
        self.logs.append(LogLine(level, message, data))

    async def credential(
        self, credential_id: uuid.UUID, accepted: frozenset[str]
    ) -> ResolvedCredential:
        resolved = await self.services.credential(self.workspace_id, credential_id, accepted)
        # Remember the values so they are redacted from everything stored about this step.
        self.secrets.extend(resolved.secret_values())
        return resolved


RunFn = Callable[[NodeContext, Any], Awaitable[NodeResult]]


@dataclass(frozen=True)
class NodeType:
    type: str
    name: str
    category: Category
    description: str
    icon: str
    config_model: builtins.type[BaseModel]
    run: RunFn | None = None
    is_trigger: bool = False
    inputs: tuple[str, ...] = ("main",)
    ports: tuple[str, ...] = ("main",)
    port_labels: Mapping[str, str] = field(default_factory=dict)
    dynamic_ports: Callable[[Mapping[str, Any]], tuple[str, ...]] | None = None
    default_retry: RetryPolicy = field(default_factory=RetryPolicy)
    default_timeout_s: int = 30
    side_effects: bool = False
    sample_output: Any = None

    @cached_property
    def template_fields(self) -> frozenset[str]:
        return frozenset(
            name
            for name, info in self.config_model.model_fields.items()
            if isinstance(info.json_schema_extra, dict) and info.json_schema_extra.get("x-template")
        )

    @cached_property
    def credential_fields(self) -> Mapping[str, frozenset[str]]:
        found: dict[str, frozenset[str]] = {}
        for name, info in self.config_model.model_fields.items():
            extra = info.json_schema_extra
            types = extra.get("x-credential-types") if isinstance(extra, dict) else None
            if isinstance(types, list):
                found[name] = frozenset(str(t) for t in types)
        return found

    def output_ports(self, config: Mapping[str, Any]) -> tuple[str, ...]:
        if self.dynamic_ports is not None:
            return self.dynamic_ports(config)
        return self.ports

    def default_port(self, config: Mapping[str, Any]) -> str | None:
        """Where a disabled node passes its input, and where `on_error: continue` routes."""
        ports = self.output_ports(config)
        if "done" in ports:
            return "done"
        if "default" in ports:
            return "default"
        return ports[0] if ports else None

    def config_schema(self) -> dict[str, Any]:
        schema: dict[str, Any] = self.config_model.model_json_schema()
        return schema
