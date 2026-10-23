"""A minimal node-type registry and an in-memory execution simulator for engine tests."""

from __future__ import annotations

import itertools
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict

from workflow_engine.engine.definition import EdgeSpec, NodeSpec, RetryPolicy, WorkflowDefinition
from workflow_engine.engine.graph import Graph
from workflow_engine.engine.routing import Completion, LoopStart, PlannedStep, Router, RoutingState


class AnyConfig(BaseModel):
    model_config = ConfigDict(extra="allow")


class HttpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    timeout_s: int = 30
    credential_id: str | None = None


@dataclass(frozen=True)
class FakeType:
    type: str
    is_trigger: bool = False
    inputs: tuple[str, ...] = ("main",)
    ports: tuple[str, ...] = ("main",)
    config_model: type[BaseModel] = AnyConfig
    template_fields: frozenset[str] = frozenset()
    credential_fields: Mapping[str, frozenset[str]] = field(default_factory=dict)
    default_retry: RetryPolicy = field(default_factory=RetryPolicy)
    default_timeout_s: int = 30

    def output_ports(self, config: Mapping[str, Any]) -> tuple[str, ...]:
        return self.ports

    def default_port(self, config: Mapping[str, Any]) -> str | None:
        return self.ports[0] if self.ports else None


REGISTRY: dict[str, FakeType] = {
    "trigger.manual": FakeType("trigger.manual", is_trigger=True, inputs=()),
    "action": FakeType("action"),
    "flow.if": FakeType("flow.if", ports=("true", "false")),
    "flow.merge": FakeType("flow.merge"),
    "flow.loop": FakeType("flow.loop", inputs=("main", "loop"), ports=("batch", "done")),
    "http": FakeType(
        "http",
        config_model=HttpConfig,
        template_fields=frozenset({"url"}),
        credential_fields={"credential_id": frozenset({"http_bearer"})},
    ),
}


def wf(
    nodes: list[tuple[str, str] | tuple[str, str, dict[str, Any]]], edges: list[str]
) -> WorkflowDefinition:
    """nodes: (id, type[, config]); edges: "source[:port] > target[:port]"."""
    specs = []
    for entry in nodes:
        node_id, node_type = entry[0], entry[1]
        config = entry[2] if len(entry) > 2 else {}  # type: ignore[misc]
        specs.append(
            NodeSpec(id=node_id, type=node_type, name=node_id.replace("_", " "), config=config)
        )
    edge_specs = []
    for index, text in enumerate(edges):
        left, right = (part.strip() for part in text.split(">"))
        source, _, source_port = left.partition(":")
        target, _, target_port = right.partition(":")
        edge_specs.append(
            EdgeSpec(
                id=f"e{index}",
                source=source,
                source_port=source_port or "main",
                target=target,
                target_port=target_port or "main",
            )
        )
    return WorkflowDefinition(nodes=specs, edges=edge_specs)


@dataclass
class SimStep:
    id: str
    node_id: str
    scope: str
    run_index: int
    status: str
    input: Any
    output: Any = None
    ports: tuple[str, ...] = ()


Behavior = Callable[[SimStep], tuple[Any, tuple[str, ...]] | LoopStart]


class Simulator:
    """Runs routing to completion in memory, the way the worker and services do in Postgres."""

    def __init__(self, definition: WorkflowDefinition, behavior: Behavior | None = None) -> None:
        self.graph = Graph(definition)
        self.behavior = behavior or (lambda step: (step.input, ("main",)))
        self.steps: list[SimStep] = []
        self._ids = itertools.count(1)

    def _new_id(self) -> str:
        return f"s{next(self._ids)}"

    def _apply(self, planned: list[PlannedStep]) -> None:
        for p in planned:
            self.steps.append(
                SimStep(p.id, p.node_id, p.scope, p.run_index, p.status, p.input, p.output, p.ports)
            )

    def run(self, trigger: str, payload: Any = None, *, max_steps: int = 500) -> RoutingState:
        state = RoutingState(trigger=trigger)
        trigger_step = SimStep(
            self._new_id(),
            trigger,
            "",
            state.next_run_index(trigger),
            "succeeded",
            payload,
            payload,
            ("main",),
        )
        self.steps.append(trigger_step)
        plan = Router(self.graph, state, new_id=self._new_id).start(
            trigger_step.id, trigger, payload
        )
        self._apply(plan.steps)
        for _ in range(max_steps):
            queued = [s for s in self.steps if s.status == "queued"]
            if not queued:
                flushed = Router(self.graph, state, new_id=self._new_id).flush()
                self._apply(flushed.steps)
                if not flushed.queued:
                    return state
                continue
            step = queued[0]
            result = self.behavior(step)
            if isinstance(result, LoopStart):
                completion = Completion(
                    step.id, step.node_id, step.scope, None, (), loop_start=result
                )
            else:
                output, ports = result
                completion = Completion(step.id, step.node_id, step.scope, output, ports)
            plan = Router(self.graph, state, new_id=self._new_id).complete(completion)
            step.status = "succeeded"
            step.output = (
                plan.completed_output if plan.completed_ports is not None else completion.output
            )
            step.ports = plan.completed_ports or completion.ports
            self._apply(plan.steps)
        raise AssertionError("simulation did not finish")

    def runs(self, node_id: str, status: str | None = None) -> list[SimStep]:
        return [
            s for s in self.steps if s.node_id == node_id and (status is None or s.status == status)
        ]
