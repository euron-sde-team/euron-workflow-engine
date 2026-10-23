"""Routing: from one finished step to the steps that run next.

Pure and deterministic: given the graph, the execution's routing state and what a step
emitted, return a plan (rows to insert) and the updated state. The worker applies the plan
inside the transaction that records the step's result.

Every edge carries one token per activation of its source: delivered (the port emitted) or
skipped (it did not). The rules, in ADR-0005 terms:

1. A node with one live input runs once per delivered token; a skipped token skips it and
   sends skipped tokens down all of its outputs, so an untaken branch is skipped to its end.
2. Any other node with several inputs (an OR join) runs once per delivered token, and is
   skipped only when every input reported skipped.
3. `flow.merge` (an AND join) waits until every live input reported in the same scope, then
   runs once with the delivered inputs, or is skipped if there were none.
4. `flow.loop` emits one batch at a time into a child scope. The token that returns on its
   back edge (delivered or skipped) completes the iteration; after the last batch the loop
   emits `done` with every result.

"Live" inputs are edges whose source can be reached from the trigger that started the
execution: a merge never waits for a branch of a trigger that did not fire.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from workflow_engine.core.ids import uuid7
from workflow_engine.engine.definition import EdgeSpec, NodeSpec
from workflow_engine.engine.graph import Graph, child_scope, parent_scope, scope_key
from workflow_engine.engine.nodetypes import LOOP, LOOP_BATCH, LOOP_DONE, MERGE

StepStatus = Literal["queued", "skipped", "succeeded"]


@dataclass(frozen=True, slots=True)
class LoopStart:
    items: list[Any]
    batch_size: int


@dataclass(frozen=True, slots=True)
class Completion:
    """What a finished step emitted. `ports` are the ports it emitted on."""

    step_id: str
    node_id: str
    scope: str
    output: Any
    ports: tuple[str, ...]
    loop_start: LoopStart | None = None


@dataclass(slots=True)
class PlannedStep:
    id: str
    node_id: str
    scope: str
    run_index: int
    status: StepStatus
    input: Any = None
    output: Any = None
    ports: tuple[str, ...] = ()
    source_step_ids: tuple[str, ...] = ()
    state: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Plan:
    steps: list[PlannedStep] = field(default_factory=list)
    # A loop decides what its own step emitted (the first batch, or `done` when empty).
    completed_output: Any = None
    completed_ports: tuple[str, ...] | None = None

    @property
    def queued(self) -> list[PlannedStep]:
        return [s for s in self.steps if s.status == "queued"]


@dataclass(slots=True)
class RoutingState:
    """Stored in `executions.state`; everything routing needs between transactions."""

    trigger: str | None = None
    vars: dict[str, Any] = field(default_factory=dict)
    joins: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    arrivals: dict[str, dict[str, bool]] = field(default_factory=dict)
    loops: dict[str, dict[str, Any]] = field(default_factory=dict)
    runs: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> RoutingState:
        data = data or {}
        return cls(
            trigger=data.get("trigger"),
            vars=dict(data.get("vars") or {}),
            joins={k: dict(v) for k, v in (data.get("joins") or {}).items()},
            arrivals={k: dict(v) for k, v in (data.get("arrivals") or {}).items()},
            loops={k: dict(v) for k, v in (data.get("loops") or {}).items()},
            runs=dict(data.get("runs") or {}),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "trigger": self.trigger,
            "vars": self.vars,
            "joins": self.joins,
            "arrivals": self.arrivals,
            "loops": self.loops,
            "runs": self.runs,
        }

    @property
    def pending(self) -> bool:
        return bool(self.joins or self.arrivals or self.loops)

    def next_run_index(self, node_id: str) -> int:
        index = self.runs.get(node_id, 0)
        self.runs[node_id] = index + 1
        return index


@dataclass(frozen=True, slots=True)
class _Token:
    edge: EdgeSpec
    scope: str
    delivered: bool
    data: Any
    step_id: str | None


def batch_payload(items: list[Any], batch_size: int, index: int, total: int) -> dict[str, Any]:
    batch = items[index * batch_size : (index + 1) * batch_size]
    payload: dict[str, Any] = {
        "batch": batch,
        "index": index,
        "batch_number": index + 1,
        "total_batches": total,
        "items_total": len(items),
    }
    if batch_size == 1 and batch:
        payload["item"] = batch[0]
    return payload


class Router:
    def __init__(
        self,
        graph: Graph,
        state: RoutingState,
        *,
        new_id: Callable[[], str] = lambda: str(uuid7()),
    ) -> None:
        self.graph = graph
        self.state = state
        self.new_id = new_id
        self.live = (
            graph.reachable_from(state.trigger)
            if state.trigger in graph.nodes
            else frozenset(graph.nodes)
        )
        self.plan = Plan()
        self._tokens: deque[_Token] = deque()

    # Entry points -------------------------------------------------------------------

    def start(self, trigger_step_id: str, trigger_id: str, payload: Any) -> Plan:
        """Route from the trigger step recorded when the execution was admitted."""
        node = self.graph.node(trigger_id)
        self._emit(node, "", payload, ("main",), trigger_step_id, skip_others=True)
        self._drain()
        return self.plan

    def complete(self, completion: Completion) -> Plan:
        node = self.graph.node(completion.node_id)
        if completion.loop_start is not None:
            self._start_loop(node, completion, completion.loop_start)
        else:
            self._emit(
                node,
                completion.scope,
                completion.output,
                completion.ports,
                completion.step_id,
                skip_others=True,
            )
        self._drain()
        return self.plan

    def flush(self) -> Plan:
        """Called when nothing is queued, running or waiting: settle what is still pending.

        Merges and OR joins first (missing inputs count as skipped). Only if that queued
        nothing are open loop iterations closed, because a queued step inside the current
        iteration would still bring its token back.
        """
        for key in list(self.state.joins):
            node_id, scope = key.split("@", 1)
            join = self.state.joins[key]
            for edge in self._live_incoming(node_id):
                join.setdefault(edge.id, {"delivered": False, "data": None, "source": edge.source})
            self._finish_join(self.graph.node(node_id), scope)
        for key in list(self.state.arrivals):
            node_id, scope = key.split("@", 1)
            arrivals = self.state.arrivals.pop(key)
            if not any(arrivals.values()):
                self._skip(self.graph.node(node_id), scope)
        self._drain()
        if not self.plan.queued:
            for key in list(self.state.loops):
                node_id, scope = key.split("@", 1)
                index = int(self.state.loops[key]["index"])
                self._continue_loop(
                    self.graph.node(node_id), child_scope(scope, node_id, index), False, None
                )
            self._drain()
        return self.plan

    # Token processing -------------------------------------------------------------

    def _live_incoming(self, node_id: str) -> list[EdgeSpec]:
        return [e for e in self.graph.main_incoming(node_id) if e.source in self.live]

    def _emit(
        self,
        node: NodeSpec,
        scope: str,
        data: Any,
        ports: tuple[str, ...],
        step_id: str | None,
        *,
        skip_others: bool,
    ) -> None:
        for edge in self.graph.outgoing.get(node.id, []):
            if edge.source_port in ports:
                self._tokens.append(_Token(edge, scope, True, data, step_id))
            elif skip_others:
                self._tokens.append(_Token(edge, scope, False, None, step_id))

    def _drain(self) -> None:
        while self._tokens:
            token = self._tokens.popleft()
            target = self.graph.node(token.edge.target)
            if self.graph.is_back_edge(token.edge):
                self._continue_loop(target, token.scope, token.delivered, token.data)
                continue
            live = self._live_incoming(target.id)
            if target.type == MERGE:
                self._join(target, token, live)
            elif len(live) <= 1:
                if token.delivered:
                    self._queue(target, token.scope, token.data, token.step_id)
                else:
                    self._skip(target, token.scope)
            else:
                self._or_join(target, token, live)

    def _or_join(self, target: NodeSpec, token: _Token, live: list[EdgeSpec]) -> None:
        key = scope_key(target.id, token.scope)
        arrivals = self.state.arrivals.setdefault(key, {})
        arrivals[token.edge.id] = arrivals.get(token.edge.id, False) or token.delivered
        if token.delivered:
            self._queue(target, token.scope, token.data, token.step_id)
        if {e.id for e in live} <= set(arrivals):
            del self.state.arrivals[key]
            if not any(arrivals.values()):
                self._skip(target, token.scope)

    def _join(self, target: NodeSpec, token: _Token, live: list[EdgeSpec]) -> None:
        key = scope_key(target.id, token.scope)
        join = self.state.joins.setdefault(key, {})
        join[token.edge.id] = {
            "delivered": token.delivered,
            "data": token.data if token.delivered else None,
            "source": token.edge.source,
            "step_id": token.step_id,
        }
        if {e.id for e in live} <= set(join):
            self._finish_join(target, token.scope)

    def _finish_join(self, target: NodeSpec, scope: str) -> None:
        join = self.state.joins.pop(scope_key(target.id, scope))
        order = {e.id: i for i, e in enumerate(self.graph.main_incoming(target.id))}
        delivered = sorted(
            ((edge_id, info) for edge_id, info in join.items() if info.get("delivered")),
            key=lambda pair: order.get(pair[0], len(order)),
        )
        if not delivered:
            self._skip(target, scope)
            return
        inputs = [{"node": info["source"], "data": info.get("data")} for _, info in delivered]
        sources = tuple(str(info["step_id"]) for _, info in delivered if info.get("step_id"))
        self._add(target, scope, "queued", step_input={"inputs": inputs}, sources=sources)

    def _queue(self, target: NodeSpec, scope: str, data: Any, source: str | None) -> None:
        self._add(target, scope, "queued", step_input=data, sources=(source,) if source else ())

    def _skip(self, target: NodeSpec, scope: str) -> None:
        self._add(target, scope, "skipped")
        for edge in self.graph.outgoing.get(target.id, []):
            if target.type == LOOP and edge.source_port != LOOP_DONE:
                continue  # a skipped loop never enters its body
            self._tokens.append(_Token(edge, scope, False, None, None))

    def _add(
        self,
        target: NodeSpec,
        scope: str,
        status: StepStatus,
        *,
        step_input: Any = None,
        output: Any = None,
        ports: tuple[str, ...] = (),
        sources: tuple[str, ...] = (),
        state: dict[str, Any] | None = None,
    ) -> PlannedStep:
        step = PlannedStep(
            id=self.new_id(),
            node_id=target.id,
            scope=scope,
            run_index=self.state.next_run_index(target.id),
            status=status,
            input=step_input,
            output=output,
            ports=ports,
            source_step_ids=sources,
            state=state or {},
        )
        self.plan.steps.append(step)
        return step

    # Loops ------------------------------------------------------------------------

    def _start_loop(self, node: NodeSpec, completion: Completion, start: LoopStart) -> None:
        size = max(1, start.batch_size)
        total = (len(start.items) + size - 1) // size
        if total == 0:
            done = {"results": [], "batches": 0, "items": 0}
            self.plan.completed_output, self.plan.completed_ports = done, (LOOP_DONE,)
            self._emit(
                node, completion.scope, done, (LOOP_DONE,), completion.step_id, skip_others=False
            )
            return
        self.state.loops[scope_key(node.id, completion.scope)] = {
            "items": start.items,
            "batch_size": size,
            "index": 0,
            "total": total,
            "results": [],
        }
        payload = batch_payload(start.items, size, 0, total)
        self.plan.completed_output, self.plan.completed_ports = payload, (LOOP_BATCH,)
        self._emit(
            node,
            child_scope(completion.scope, node.id, 0),
            payload,
            (LOOP_BATCH,),
            completion.step_id,
            skip_others=False,
        )

    def _continue_loop(self, node: NodeSpec, body_scope: str, delivered: bool, data: Any) -> None:
        scope = parent_scope(body_scope)
        key = scope_key(node.id, scope)
        loop = self.state.loops.get(key)
        if loop is None or body_scope != child_scope(scope, node.id, int(loop["index"])):
            return  # a stale token from an iteration that is already closed
        if delivered:
            loop["results"].append(data)
        loop["index"] = index = int(loop["index"]) + 1
        if index < int(loop["total"]):
            payload = batch_payload(
                loop["items"], int(loop["batch_size"]), index, int(loop["total"])
            )
            step = self._add(
                node,
                scope,
                "succeeded",
                output=payload,
                ports=(LOOP_BATCH,),
                state={"iteration": index},
            )
            self._emit(
                node,
                child_scope(scope, node.id, index),
                payload,
                (LOOP_BATCH,),
                step.id,
                skip_others=False,
            )
            return
        del self.state.loops[key]
        done = {"results": loop["results"], "batches": loop["total"], "items": len(loop["items"])}
        step = self._add(node, scope, "succeeded", output=done, ports=(LOOP_DONE,))
        self._emit(node, scope, done, (LOOP_DONE,), step.id, skip_others=False)
