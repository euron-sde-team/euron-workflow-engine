"""The engine's transactional core: every queue state change goes through this class.

One `Engine` wraps one database session (one transaction). The rules it keeps:

- Lock order is always execution, then steps; a workflow row is locked only to admit its
  own executions, and admissions caused by a worker transaction run after its commit, in
  their own transaction. Sweeps lock executions with SKIP LOCKED so they never queue
  behind a completion.
- A worker may only change a step it holds (`locked_by = worker AND status = running`).
  When that guard matches nothing the claim was lost and the result is dropped.
- Side effects that are not database writes (wake-ups, cancel signals, follow-up
  admissions) happen in `commit()`, after the transaction succeeded.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import orjson
from sqlalchemy.ext.asyncio import AsyncSession

from workflow_engine.core import metrics
from workflow_engine.core.ids import uuid7
from workflow_engine.core.logging import get_logger
from workflow_engine.engine.backoff import retry_delay_ms
from workflow_engine.engine.definition import NodeSpec, RetryPolicy
from workflow_engine.engine.expressions import ExpressionError, evaluate, truthy
from workflow_engine.engine.nodetypes import STOP
from workflow_engine.engine.routing import Completion, Plan, Router, RoutingState
from workflow_engine.models import (
    DeadLetter,
    Event,
    Execution,
    ExecutionLog,
    ExecutionStep,
    Workflow,
    WorkflowVersion,
)
from workflow_engine.models.enums import (
    DeadLetterStatus,
    EventSource,
    ExecutionMode,
    ExecutionStatus,
    StepStatus,
    TriggerKind,
)
from workflow_engine.nodes.base import LogLine, NodeError, NodeResult
from workflow_engine.nodes.triggers import EventTriggerConfig
from workflow_engine.repositories.executions import (
    DeadLetterRepository,
    ExecutionRepository,
    LogRepository,
    StepRepository,
)
from workflow_engine.repositories.workflows import TriggerRepository
from workflow_engine.services.container import CompiledDefinition, Container
from workflow_engine.services.principal import Principal

log = get_logger("wfe.engine")
REDACTED = "[redacted]"
MAX_SETTLE_ROUNDS = 50


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class StartResult:
    execution: Execution
    duplicate: bool


@dataclass(slots=True)
class StepOutcome:
    """What a worker hands back after running one step."""

    started: datetime
    finished: datetime
    logs: list[LogLine] = field(default_factory=list)
    secrets: list[str] = field(default_factory=list)


def redact(value: Any, secrets: Sequence[str]) -> Any:
    """Replace every occurrence of a secret inside a JSON value with [redacted]."""
    if not secrets or value is None:
        return value
    text = orjson.dumps(value, option=orjson.OPT_NON_STR_KEYS).decode()
    changed = False
    for secret in sorted(set(secrets), key=len, reverse=True):
        escaped = orjson.dumps(secret).decode()[1:-1]
        if escaped and escaped in text:
            text = text.replace(escaped, REDACTED)
            changed = True
    return orjson.loads(text) if changed else value


class Engine:
    def __init__(self, container: Container, session: AsyncSession) -> None:
        self.c = container
        self.session = session
        self.executions = ExecutionRepository(session)
        self.steps = StepRepository(session)
        self.logs = LogRepository(session)
        self.letters = DeadLetterRepository(session)
        self.triggers = TriggerRepository(session)
        self._wake = False
        self._cancelled: set[uuid.UUID] = set()
        self._admit_later: set[uuid.UUID] = set()
        self._finished: list[tuple[str, float | None]] = []

    # Transaction boundary -------------------------------------------------------------

    def wake_after_commit(self) -> None:
        self._wake = True

    def admit_after_commit(self, workflow_id: uuid.UUID) -> None:
        self._admit_later.add(workflow_id)

    def cancel_after_commit(self, execution_id: uuid.UUID) -> None:
        self._cancelled.add(execution_id)

    async def commit(self) -> None:
        await self.session.commit()
        for status, seconds in self._finished:
            metrics.EXECUTIONS_FINISHED.labels(status).inc()
            if seconds is not None:
                metrics.EXECUTION_DURATION.observe(seconds)
        self._finished.clear()
        for workflow_id in sorted(self._admit_later):
            # Each follow-up admission is its own transaction holding one workflow lock,
            # so two workers finishing executions of different workflows cannot deadlock.
            async with self.c.db.session() as session:
                follow_up = Engine(self.c, session)
                await follow_up.admit(workflow_id)
                await follow_up.commit()
        self._admit_later.clear()
        for execution_id in self._cancelled:
            await self.c.signals.cancel(execution_id)
        self._cancelled.clear()
        if self._wake:
            self._wake = False
            await self.c.signals.wake()

    # Definitions and sizes ------------------------------------------------------------

    async def compiled(self, version_id: uuid.UUID) -> CompiledDefinition:
        cached = self.c.definitions.get(version_id)
        if cached is not None:
            return cached
        version = await self.session.get(WorkflowVersion, version_id)
        if version is None:  # pragma: no cover - guarded by foreign keys
            raise LookupError(f"version {version_id} is missing")
        return self.c.definitions.load(version_id, version.definition)

    def sized(self, value: Any, what: str) -> Any:
        size = len(orjson.dumps(value, option=orjson.OPT_NON_STR_KEYS))
        if size > self.c.settings.max_payload_bytes:
            raise NodeError(
                "payload_too_large",
                f"The {what} is {size // 1024} KB, more than the {self.c.settings.max_payload_kb} "
                "KB this deployment allows. Store large data in S3 and pass its key instead.",
            )
        return value

    def _policy(self, compiled: CompiledDefinition, node: NodeSpec) -> tuple[RetryPolicy, int]:
        node_type = self.c.registry[node.type]
        return node.retry or node_type.default_retry, node.timeout_s or node_type.default_timeout_s

    # Starting and admitting -----------------------------------------------------------

    async def start(
        self,
        *,
        workflow: Workflow,
        version_id: uuid.UUID,
        trigger_node_id: str,
        payload: Any,
        mode: ExecutionMode,
        trigger_kind: TriggerKind,
        idempotency_key: str | None = None,
        principal: Principal | None = None,
        event_id: uuid.UUID | None = None,
        event_depth: int = 0,
        retry_of_id: uuid.UUID | None = None,
        admit_now: bool = True,
    ) -> StartResult:
        """Record a queued execution (deduplicated by key) and admit it if a slot is free."""
        payload = self.sized(payload, "trigger payload")
        inserted = await self.executions.insert(
            {
                "id": uuid7(),
                "workspace_id": workflow.workspace_id,
                "workflow_id": workflow.id,
                "version_id": version_id,
                "status": ExecutionStatus.QUEUED,
                "mode": mode,
                "trigger_kind": trigger_kind,
                "trigger_node_id": trigger_node_id,
                "trigger_payload": payload,
                "idempotency_key": idempotency_key,
                "event_id": event_id,
                "event_depth": event_depth,
                "retry_of_id": retry_of_id,
                "state": RoutingState(trigger=trigger_node_id).to_json(),
                "created_by_user_id": principal.user_id if principal else None,
                "created_by_api_key_id": principal.api_key_id if principal else None,
            },
            idempotent=idempotency_key is not None,
        )
        if inserted is None:
            existing = await self.executions.by_key(workflow.id, idempotency_key or "")
            if existing is None:  # pragma: no cover - the conflict proves it exists
                raise LookupError("idempotency conflict without a row")
            return StartResult(existing, duplicate=True)
        metrics.EXECUTIONS_STARTED.labels(trigger_kind).inc()
        if admit_now:
            await self.admit(workflow.id)
        else:
            self._admit_later.add(workflow.id)
        # The identity map already holds the admitted row with its unflushed changes;
        # reloading it from the database here would silently discard them.
        execution = await self.session.get(Execution, inserted)
        if execution is None:  # pragma: no cover
            raise LookupError("inserted execution vanished")
        return StartResult(execution, duplicate=False)

    async def admit(self, workflow_id: uuid.UUID) -> int:
        """Start queued executions of a workflow, oldest first, up to its concurrency limit."""
        workflow = await self.executions.lock_workflow(workflow_id)
        if workflow is None:
            return 0
        free = 100
        if workflow.concurrency_limit is not None:
            free = workflow.concurrency_limit - await self.executions.running_count(workflow_id)
            if free <= 0:
                return 0
        admitted = 0
        for execution in await self.executions.queued_for_admission(workflow_id, free):
            await self._begin(execution, workflow)
            admitted += 1
        return admitted

    async def _begin(self, execution: Execution, workflow: Workflow) -> None:
        now = utcnow()
        execution.status = ExecutionStatus.RUNNING
        execution.started_at = now
        execution.deadline_at = now + timedelta(seconds=workflow.timeout_s)
        compiled = await self.compiled(execution.version_id)
        state = RoutingState.from_json(execution.state)
        trigger = compiled.graph.node(execution.trigger_node_id)
        trigger_step = ExecutionStep(
            id=uuid7(),
            execution_id=execution.id,
            workspace_id=execution.workspace_id,
            node_id=trigger.id,
            node_type=trigger.type,
            node_name=trigger.name,
            run_index=state.next_run_index(trigger.id),
            scope="",
            status=StepStatus.SUCCEEDED,
            attempt=1,
            max_attempts=1,
            output=execution.trigger_payload,
            ports=["main"],
            timeout_s=0,
            started_at=now,
            finished_at=now,
            duration_ms=0,
        )
        self.session.add(trigger_step)
        plan = Router(compiled.graph, state).start(
            str(trigger_step.id), trigger.id, execution.trigger_payload
        )
        self._apply(execution, compiled, plan, now)
        execution.state = state.to_json()
        await self._settle(execution, compiled, state)

    def _apply(
        self, execution: Execution, compiled: CompiledDefinition, plan: Plan, now: datetime
    ) -> None:
        rows = []
        for planned in plan.steps:
            node = compiled.graph.node(planned.node_id)
            policy, timeout = self._policy(compiled, node)
            done = planned.status in ("succeeded", "skipped")
            rows.append(
                ExecutionStep(
                    id=uuid.UUID(planned.id),
                    execution_id=execution.id,
                    workspace_id=execution.workspace_id,
                    node_id=node.id,
                    node_type=node.type,
                    node_name=node.name,
                    run_index=planned.run_index,
                    scope=planned.scope,
                    status=planned.status,
                    attempt=1 if planned.status == "succeeded" else 0,
                    max_attempts=policy.max_attempts,
                    input=planned.input,
                    output=planned.output,
                    ports=list(planned.ports),
                    state=planned.state,
                    available_at=now,
                    timeout_s=timeout,
                    started_at=now if planned.status == "succeeded" else None,
                    finished_at=now if done else None,
                    duration_ms=0 if planned.status == "succeeded" else None,
                )
            )
            if planned.status == "queued":
                self._wake = True
        self.session.add_all(rows)

    # Settling and finishing -----------------------------------------------------------

    async def _settle(
        self, execution: Execution, compiled: CompiledDefinition, state: RoutingState
    ) -> None:
        for _ in range(MAX_SETTLE_ROUNDS):
            await self.session.flush()
            counts = await self.steps.active_counts(execution.id)
            if counts.queued or counts.running:
                execution.status = ExecutionStatus.RUNNING
                return
            if counts.waiting:
                execution.status = ExecutionStatus.WAITING
                return
            plan = Router(compiled.graph, state).flush()
            if not plan.steps:
                await self._finish(execution, compiled)
                return
            self._apply(execution, compiled, plan, utcnow())
            execution.state = state.to_json()
        log.error("settle_did_not_converge", execution_id=str(execution.id))
        await self.fail_execution(
            execution,
            None,
            {"code": "routing_error", "message": "The workflow did not settle; check its loops."},
        )

    async def _finish(self, execution: Execution, compiled: CompiledDefinition) -> None:
        now = utcnow()
        leaves = [n for n in compiled.graph.nodes if not compiled.graph.outgoing.get(n)]
        execution.output = await self.steps.final_output(execution.id, leaves)
        execution.status = ExecutionStatus.SUCCEEDED
        execution.error = None
        self._close(execution, now)
        await self._system_event(execution, "execution.succeeded")

    def _close(self, execution: Execution, now: datetime) -> None:
        execution.finished_at = now
        started = execution.started_at or execution.created_at
        execution.duration_ms = max(0, int((now - started).total_seconds() * 1000))
        self._finished.append((execution.status, execution.duration_ms / 1000))
        self._admit_later.add(execution.workflow_id)

    async def fail_execution(
        self,
        execution: Execution,
        step: ExecutionStep | None,
        error: dict[str, Any],
    ) -> None:
        now = utcnow()
        running = await self.steps.cancel_active(
            execution.id,
            {"code": "upstream_failure", "message": "Cancelled because another step failed."},
            except_id=step.id if step else None,
        )
        if running:
            self._cancelled.add(execution.id)
        execution.status = ExecutionStatus.FAILED
        execution.error = {
            **error,
            **({"node_id": step.node_id, "step_id": str(step.id)} if step else {}),
        }
        self._close(execution, now)
        if step is not None:
            self.letters.add(
                DeadLetter(
                    workspace_id=execution.workspace_id,
                    workflow_id=execution.workflow_id,
                    execution_id=execution.id,
                    step_id=step.id,
                    node_id=step.node_id,
                    node_name=step.node_name,
                    error=step.error or error,
                    input=step.input,
                    status=DeadLetterStatus.OPEN,
                )
            )
            metrics.DEAD_LETTERS.inc()
        await self._system_event(execution, "execution.failed")

    # Steps: completion, retry, suspension -------------------------------------------

    def _logs(self, step: ExecutionStep, lines: Sequence[LogLine], secrets: Sequence[str]) -> None:
        self.logs.add_many(
            [
                ExecutionLog(
                    execution_id=step.execution_id,
                    step_id=step.id,
                    workspace_id=step.workspace_id,
                    level=line.level,
                    message=str(redact(line.message, secrets))[:2000],
                    data=redact(line.data, secrets) or {},
                )
                for line in lines
            ]
        )

    def _timing(self, step: ExecutionStep, outcome: StepOutcome) -> None:
        step.started_at = outcome.started
        step.finished_at = outcome.finished
        step.duration_ms = max(0, int((outcome.finished - outcome.started).total_seconds() * 1000))
        metrics.STEP_DURATION.labels(step.node_type).observe(step.duration_ms / 1000)

    async def complete(
        self,
        step_id: uuid.UUID,
        worker_id: str,
        result: NodeResult,
        outcome: StepOutcome,
    ) -> bool:
        """Record a successful step and route on. False when the claim was lost."""
        held = await self._held(step_id, worker_id)
        if held is None:
            return False
        execution, step = held
        compiled = await self.compiled(execution.version_id)
        try:
            output = self.sized(redact(result.output, outcome.secrets), "node output")
        except NodeError as exc:
            await self.record_failure(execution, compiled, step, exc, outcome, allow_retry=False)
            return True
        state = RoutingState.from_json(execution.state)
        if result.vars:
            state.vars.update(redact(result.vars, outcome.secrets))
        if result.events:
            published = await self._publish_from_step(execution, step, result.events)
            if isinstance(output, dict):
                output = {**output, **published}
        if result.suspend_until is not None:
            step.status = StepStatus.WAITING
            step.available_at = result.suspend_until
            step.output = output
            step.locked_by = None
            step.heartbeat_at = None
            self._timing(step, outcome)
            step.finished_at = None
            self._logs(step, outcome.logs, outcome.secrets)
            execution.state = state.to_json()
            metrics.STEPS.labels(step.node_type, "waiting").inc()
            await self._settle(execution, compiled, state)
            return True
        plan = Router(compiled.graph, state).complete(
            Completion(
                str(step.id), step.node_id, step.scope, output, result.ports, result.loop_start
            )
        )
        step.status = StepStatus.SUCCEEDED
        step.output = output if plan.completed_ports is None else plan.completed_output
        step.ports = list(plan.completed_ports or result.ports)
        step.error = None
        self._timing(step, outcome)
        self._logs(step, outcome.logs, outcome.secrets)
        metrics.STEPS.labels(step.node_type, "succeeded").inc()
        self._apply(execution, compiled, plan, utcnow())
        execution.state = state.to_json()
        await self._settle(execution, compiled, state)
        return True

    async def fail(
        self, step_id: uuid.UUID, worker_id: str, error: NodeError, outcome: StepOutcome
    ) -> bool:
        """Record a failed attempt: retry with backoff, continue, or fail the execution."""
        held = await self._held(step_id, worker_id)
        if held is None:
            return False
        execution, step = held
        compiled = await self.compiled(execution.version_id)
        await self.record_failure(execution, compiled, step, error, outcome, allow_retry=True)
        return True

    async def record_failure(
        self,
        execution: Execution,
        compiled: CompiledDefinition,
        step: ExecutionStep,
        error: NodeError,
        outcome: StepOutcome | None,
        *,
        allow_retry: bool,
    ) -> None:
        node = compiled.graph.node(step.node_id)
        policy, _ = self._policy(compiled, node)
        body = redact(error.to_json(), outcome.secrets if outcome else [])
        step.error = {**body, "attempt": step.attempt}
        if outcome is not None:
            self._timing(step, outcome)
            self._logs(step, outcome.logs, outcome.secrets)
        retry = (
            allow_retry
            and error.retryable
            and step.attempt < step.max_attempts
            and node.type != STOP
        )
        if retry:
            delay_ms = retry_delay_ms(policy, step.attempt)
            if error.retry_after_s is not None:
                delay_ms = max(delay_ms, int(error.retry_after_s * 1000))
            step.status = StepStatus.QUEUED
            step.available_at = utcnow() + timedelta(milliseconds=delay_ms)
            step.locked_by = None
            step.heartbeat_at = None
            step.finished_at = None
            self.logs.add_many(
                [
                    ExecutionLog(
                        execution_id=step.execution_id,
                        step_id=step.id,
                        workspace_id=step.workspace_id,
                        level="warn",
                        message=(
                            f"Attempt {step.attempt} of {step.max_attempts} failed "
                            f"({error.code}); retrying in {delay_ms / 1000:.1f} s"
                        ),
                        data={"code": error.code, "delay_ms": delay_ms, "attempt": step.attempt},
                    )
                ]
            )
            metrics.STEPS.labels(step.node_type, "retried").inc()
            metrics.STEP_RETRIES.labels(step.node_type).inc()
            self._wake = True
            return
        step.status = StepStatus.FAILED
        metrics.STEPS.labels(step.node_type, "failed").inc()
        if node.on_error == "continue" and node.type != STOP:
            node_type = self.c.registry[node.type]
            port = node_type.default_port(node.config)
            state = RoutingState.from_json(execution.state)
            plan = Router(compiled.graph, state).complete(
                Completion(
                    str(step.id),
                    step.node_id,
                    step.scope,
                    {"error": step.error, "input": step.input},
                    (port,) if port else (),
                )
            )
            step.output = {"error": step.error, "input": step.input}
            step.ports = [port] if port else []
            self._apply(execution, compiled, plan, utcnow())
            execution.state = state.to_json()
            await self._settle(execution, compiled, state)
            return
        await self.fail_execution(execution, step, {"code": error.code, "message": error.message})

    async def _held(
        self, step_id: uuid.UUID, worker_id: str
    ) -> tuple[Execution, ExecutionStep] | None:
        probe = await self.session.get(ExecutionStep, step_id)
        if probe is None:
            return None
        execution = await self.executions.lock(probe.execution_id)
        step = await self.steps.held(step_id, worker_id)
        if execution is None or step is None:
            return None
        if execution.status not in (ExecutionStatus.RUNNING, ExecutionStatus.WAITING):
            return None
        return execution, step

    # Events ----------------------------------------------------------------------------

    async def publish_event(
        self,
        *,
        workspace_id: uuid.UUID,
        name: str,
        payload: Any,
        source: EventSource,
        source_execution_id: uuid.UUID | None = None,
        depth: int = 0,
        admit_now: bool = False,
    ) -> tuple[Event, list[Execution]]:
        """Record an event and start every active workflow that listens for it."""
        event = Event(
            id=uuid7(),
            workspace_id=workspace_id,
            name=name,
            payload=payload,
            source=source,
            source_execution_id=source_execution_id,
            depth=depth,
        )
        self.session.add(event)
        await self.session.flush()
        metrics.EVENTS_PUBLISHED.labels(source).inc()
        started: list[Execution] = []
        if depth > self.c.settings.event_max_depth:
            log.warning("event_chain_too_deep", event_name=name, depth=depth)
            return event, started
        context = {"event": name, "payload": payload, "source": str(source)}
        triggers = sorted(
            await self.triggers.for_event(workspace_id, name), key=lambda t: t.workflow_id
        )
        for trigger in triggers:
            config = EventTriggerConfig.model_validate(trigger.config)
            if config.filter:
                try:
                    if not truthy(evaluate(config.filter, context)):
                        continue
                except ExpressionError as exc:
                    log.warning("event_filter_failed", trigger=str(trigger.id), error=str(exc))
                    continue
            workflow = await self.session.get(Workflow, trigger.workflow_id)
            if workflow is None or not workflow.active:
                continue
            result = await self.start(
                workflow=workflow,
                version_id=trigger.version_id,
                trigger_node_id=trigger.node_id,
                payload={
                    "event": name,
                    "payload": payload,
                    "event_id": str(event.id),
                    "source": str(source),
                },
                mode=ExecutionMode.PRODUCTION,
                trigger_kind=TriggerKind.EVENT,
                event_id=event.id,
                event_depth=depth,
                admit_now=admit_now,
            )
            started.append(result.execution)
        event.matched = len(started)
        return event, started

    async def _publish_from_step(
        self, execution: Execution, step: ExecutionStep, events: list[tuple[str, Any]]
    ) -> dict[str, Any]:
        published: dict[str, Any] = {}
        for name, payload in events:
            event, started = await self.publish_event(
                workspace_id=execution.workspace_id,
                name=name,
                payload=payload,
                source=EventSource.WORKFLOW,
                source_execution_id=execution.id,
                depth=execution.event_depth + 1,
            )
            published = {"event_id": str(event.id), "matched": len(started)}
        return published

    async def _system_event(self, execution: Execution, name: str) -> None:
        trigger_event = (
            execution.trigger_payload.get("event", "")
            if isinstance(execution.trigger_payload, dict)
            else ""
        )
        # A failure handler that fails must not trigger itself: executions started by an
        # execution.* event never publish execution.* events.
        if str(trigger_event).startswith("execution.") or execution.mode == ExecutionMode.TEST:
            return
        workflow = await self.session.get(Workflow, execution.workflow_id)
        await self.publish_event(
            workspace_id=execution.workspace_id,
            name=name,
            payload={
                "execution_id": str(execution.id),
                "workflow_id": str(execution.workflow_id),
                "workflow_name": workflow.name if workflow else "",
                "status": execution.status,
                "error": execution.error,
                "trigger_kind": execution.trigger_kind,
                "started_at": execution.started_at.isoformat() if execution.started_at else None,
                "finished_at": execution.finished_at.isoformat() if execution.finished_at else None,
                "duration_ms": execution.duration_ms,
                "url": f"{self.c.settings.web_url}/executions/{execution.id}",
            },
            source=EventSource.SYSTEM,
            source_execution_id=execution.id,
            depth=execution.event_depth + 1,
        )
