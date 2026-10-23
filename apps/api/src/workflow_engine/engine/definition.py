"""The workflow definition document: nodes, edges and per-node policies.

Drafts, published versions, exports and the editor all exchange exactly this shape. The
checksum is computed over a canonical JSON form (sorted keys, no whitespace), so two
definitions that differ only in key order are the same version.
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal

import orjson
from pydantic import BaseModel, ConfigDict, Field, model_validator

NODE_ID_PATTERN = r"^[a-z][a-z0-9_]{0,47}$"
MAX_NODES = 200
MAX_EDGES = 500
MAX_DEFINITION_BYTES = 256 * 1024


class RetryPolicy(BaseModel):
    """How a failed attempt is retried: exponential backoff, capped, with equal jitter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_attempts: int = Field(default=1, ge=1, le=10)
    initial_delay_ms: int = Field(default=1000, ge=100, le=600_000)
    max_delay_ms: int = Field(default=60_000, ge=100, le=3_600_000)
    multiplier: float = Field(default=2.0, ge=1.0, le=10.0)
    jitter: bool = True

    @model_validator(mode="after")
    def _ordered(self) -> RetryPolicy:
        if self.max_delay_ms < self.initial_delay_ms:
            raise ValueError("max_delay_ms must be at least initial_delay_ms")
        return self


class Position(BaseModel):
    model_config = ConfigDict(extra="ignore")

    x: float = 0.0
    y: float = 0.0


class NodeSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(pattern=NODE_ID_PATTERN, description="Stable id, used as steps.<id>.")
    type: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=80)
    config: dict[str, Any] = Field(default_factory=dict)
    position: Position = Field(default_factory=Position)
    retry: RetryPolicy | None = None
    timeout_s: int | None = Field(default=None, ge=1, le=900)
    on_error: Literal["fail", "continue"] = "fail"
    disabled: bool = False
    notes: str = Field(default="", max_length=2000)


class EdgeSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=48)
    source_port: str = Field(default="main", min_length=1, max_length=48)
    target: str = Field(min_length=1, max_length=48)
    target_port: str = Field(default="main", min_length=1, max_length=48)


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: Literal[1] = 1
    nodes: list[NodeSpec] = Field(default_factory=list, max_length=MAX_NODES)
    edges: list[EdgeSpec] = Field(default_factory=list, max_length=MAX_EDGES)

    def node(self, node_id: str) -> NodeSpec | None:
        return next((n for n in self.nodes if n.id == node_id), None)


def canonical_json(definition: WorkflowDefinition) -> bytes:
    return orjson.dumps(definition.model_dump(mode="json"), option=orjson.OPT_SORT_KEYS)


def checksum(definition: WorkflowDefinition) -> str:
    return hashlib.sha256(canonical_json(definition)).hexdigest()


def empty_definition() -> WorkflowDefinition:
    """A new workflow: one manual trigger, ready for the first node."""
    return WorkflowDefinition(
        nodes=[
            NodeSpec(
                id="manual_trigger",
                type="trigger.manual",
                name="Run manually",
                config={"sample_payload": {}},
                position=Position(x=80, y=200),
            )
        ]
    )
