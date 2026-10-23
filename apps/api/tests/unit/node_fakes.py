"""Fake services for running node types in unit tests."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from workflow_engine.core.config import Settings
from workflow_engine.engine.definition import NodeSpec
from workflow_engine.integrations.http import NetworkPolicy
from workflow_engine.nodes import runner
from workflow_engine.nodes.base import NodeContext, NodeError, NodeResult, ResolvedCredential
from workflow_engine.nodes.registry import REGISTRY

NOW = datetime(2026, 10, 23, 8, 0, tzinfo=UTC)
WORKSPACE = uuid.UUID("01900000-0000-7000-8000-000000000001")


class Recorder:
    """A stand-in boto3 client: records calls, returns canned responses or raises."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses = responses or {}

    def __getattr__(self, name: str) -> Any:
        def call(**kwargs: Any) -> Any:
            self.calls.append((name, kwargs))
            response = self.responses.get(name, {})
            if isinstance(response, Exception):
                raise response
            return response(**kwargs) if callable(response) else response

        return call


@dataclass
class FakeAws:
    s3_client: Recorder = field(default_factory=Recorder)
    sqs_client: Recorder = field(default_factory=Recorder)
    ses_client: Recorder = field(default_factory=Recorder)

    def s3(self) -> Recorder:
        return self.s3_client

    def sqs(self) -> Recorder:
        return self.sqs_client

    def ses(self) -> Recorder:
        return self.ses_client


@dataclass
class FakeServices:
    settings: Settings = field(
        default_factory=lambda: Settings(
            workflow_data_bucket="wfe-data",
            sqs_allowed_queues=["order-events", "invoices.fifo"],
            mail_from="Automations <automations@wfe.example.test>",
        )
    )
    http: httpx.AsyncClient = field(default_factory=httpx.AsyncClient)
    aws: Any = field(default_factory=FakeAws)
    network_policy: NetworkPolicy = field(default_factory=NetworkPolicy)
    credentials: dict[uuid.UUID, ResolvedCredential] = field(default_factory=dict)

    def add_credential(self, kind: str, **values: Any) -> uuid.UUID:
        credential_id = uuid.uuid4()
        self.credentials[credential_id] = ResolvedCredential(credential_id, kind, values)
        return credential_id

    async def credential(
        self, workspace_id: uuid.UUID, credential_id: uuid.UUID, accepted: frozenset[str]
    ) -> ResolvedCredential:
        resolved = self.credentials.get(credential_id)
        if resolved is None or resolved.type not in accepted:
            raise NodeError("credential_unavailable", "missing credential")
        return resolved


def context(input_value: Any = None, **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "trigger": {},
        "input": input_value,
        "steps": {},
        "vars": {},
        "env": {},
        "execution": {"id": "e1", "mode": "test"},
        "now": NOW.isoformat(),
    }
    base.update(extra)
    return base


async def run_node(
    node_type: str,
    config: dict[str, Any],
    input_value: Any = None,
    *,
    services: FakeServices | None = None,
    resumed: bool = False,
    **context_extra: Any,
) -> tuple[NodeResult, NodeContext]:
    spec = REGISTRY[node_type]
    ctx = NodeContext(
        workspace_id=WORKSPACE,
        execution_id=None,
        step_id=None,
        node=NodeSpec(id="node", type=node_type, name="Node", config=config),
        input=input_value,
        expression_context=context(input_value, **context_extra),
        now=NOW,
        attempt=1,
        services=services or FakeServices(),  # type: ignore[arg-type]
        resumed=resumed,
        test_run=True,
    )
    result = await runner.execute(spec, ctx)
    return result, ctx
