"""Running one claimed step: build its context, run the node, record what happened.

The node runs outside any database transaction (a slow API call must not hold row locks).
Its result is recorded afterwards in one transaction that re-checks the claim, so a step
that was cancelled, reaped or failed by a deadline while it ran is discarded, not written.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import DBAPIError, OperationalError

from workflow_engine.core.logging import get_logger
from workflow_engine.engine import templates
from workflow_engine.engine.expressions import iso
from workflow_engine.engine.routing import RoutingState
from workflow_engine.models import Execution, ExecutionStep
from workflow_engine.nodes import runner
from workflow_engine.nodes.base import LogLine, NodeContext, NodeError, NodeResult
from workflow_engine.repositories.executions import StepRepository
from workflow_engine.repositories.variables import VariableRepository
from workflow_engine.services.container import Container
from workflow_engine.services.engine import Engine, StepOutcome
from workflow_engine.services.node_services import RuntimeServices

log = get_logger("wfe.steps")
RECORD_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class ClaimedStep:
    id: uuid.UUID
    execution_id: uuid.UUID
    workspace_id: uuid.UUID
    node_id: str
    node_type: str
    scope: str
    attempt: int
    max_attempts: int
    input: Any
    state: dict[str, Any]
    timeout_s: int

    @classmethod
    def of(cls, row: ExecutionStep) -> ClaimedStep:
        return cls(
            id=row.id,
            execution_id=row.execution_id,
            workspace_id=row.workspace_id,
            node_id=row.node_id,
            node_type=row.node_type,
            scope=row.scope,
            attempt=row.attempt,
            max_attempts=row.max_attempts,
            input=row.input,
            state=dict(row.state or {}),
            timeout_s=row.timeout_s,
        )


@dataclass(slots=True)
class Prepared:
    context: NodeContext
    disabled: bool
    default_port: str | None
    logs: list[LogLine] = field(default_factory=list)


def expression_context(
    execution: Execution,
    step_input: Any,
    outputs: dict[str, Any],
    env: dict[str, str],
    now: datetime,
    attempt: int,
) -> dict[str, Any]:
    state = RoutingState.from_json(execution.state)
    return {
        "trigger": execution.trigger_payload,
        "input": step_input,
        "steps": outputs,
        "vars": state.vars,
        "env": env,
        "execution": {
            "id": str(execution.id),
            "workflow_id": str(execution.workflow_id),
            "mode": execution.mode,
            "trigger_kind": execution.trigger_kind,
            "started_at": iso(execution.started_at) if execution.started_at else None,
            "attempt": attempt,
        },
        "now": iso(now),
    }


class StepRunner:
    def __init__(self, container: Container, worker_id: str) -> None:
        self.c = container
        self.worker_id = worker_id
        self.services = RuntimeServices(container)
        # Steps whose node finished and whose result is being written: a heartbeat that
        # misses them is the write itself, not a lost claim, so they are not cancelled.
        self.recording: set[uuid.UUID] = set()

    async def claim(self, limit: int) -> list[ClaimedStep]:
        async with self.c.db.session() as session:
            rows = await StepRepository(session).claim(self.worker_id, limit)
            await session.commit()
        return [ClaimedStep.of(row) for row in rows]

    async def prepare(self, step: ClaimedStep, now: datetime) -> Prepared | None:
        async with self.c.db.session() as session:
            execution = await session.get(Execution, step.execution_id)
            if execution is None:
                return None
            compiled = await Engine(self.c, session).compiled(execution.version_id)
            node = compiled.graph.nodes.get(step.node_id)
            if node is None:
                return None
            references = sorted(templates.step_references(node.config))
            outputs = await StepRepository(session).latest_outputs(execution.id, references)
            env = await VariableRepository(session).as_dict(execution.workspace_id)
        node_type = self.c.registry[node.type]
        context = NodeContext(
            workspace_id=step.workspace_id,
            execution_id=step.execution_id,
            step_id=step.id,
            node=node,
            input=step.input,
            expression_context=expression_context(
                execution, step.input, outputs, env, now, step.attempt
            ),
            now=now,
            attempt=step.attempt,
            services=self.services,
            resumed=bool(step.state.get("resumed")),
        )
        return Prepared(context, node.disabled, node_type.default_port(node.config))

    async def execute(self, step: ClaimedStep) -> None:
        """Run a claimed step to an outcome. Cancellation (a lost claim) propagates."""
        started = datetime.now(UTC)
        prepared = await self.prepare(step, started)
        if prepared is None:
            log.warning("step_without_definition", step_id=str(step.id))
            return
        ctx = prepared.context
        node_type = self.c.registry[ctx.node.type]
        result: NodeResult | None = None
        error: NodeError | None = None
        if prepared.disabled:
            ctx.log("info", "The node is disabled: its input passes through unchanged")
            port = prepared.default_port
            result = NodeResult(output=ctx.input, ports=(port,) if port else ())
        else:
            try:
                async with asyncio.timeout(step.timeout_s):
                    result = await runner.execute(node_type, ctx)
            except NodeError as exc:
                error = exc
            except TimeoutError:
                error = NodeError(
                    "timeout", f"The step ran longer than {step.timeout_s} s.", retryable=True
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("node_crashed", node_type=ctx.node.type, step_id=str(step.id))
                error = NodeError(
                    "internal_error", f"{type(exc).__name__}: {exc}"[:500], retryable=True
                )
        outcome = StepOutcome(
            started=started, finished=datetime.now(UTC), logs=ctx.logs, secrets=ctx.secrets
        )
        self.recording.add(step.id)
        try:
            await self.record(step, result, error, outcome)
        finally:
            self.recording.discard(step.id)

    async def record(
        self,
        step: ClaimedStep,
        result: NodeResult | None,
        error: NodeError | None,
        outcome: StepOutcome,
    ) -> None:
        for attempt in range(1, RECORD_ATTEMPTS + 1):
            try:
                async with self.c.db.session() as session:
                    engine = Engine(self.c, session)
                    if error is not None:
                        recorded = await engine.fail(step.id, self.worker_id, error, outcome)
                    elif result is not None:
                        recorded = await engine.complete(step.id, self.worker_id, result, outcome)
                    else:  # pragma: no cover - one of them is always set
                        return
                    if not recorded:
                        await session.rollback()
                        log.info("claim_lost", step_id=str(step.id))
                        return
                    await engine.commit()
                return
            except (OperationalError, DBAPIError) as exc:
                # Deadlocks and serialization failures are transient; anything else stays
                # running until the reaper hands the step to another attempt.
                log.warning(
                    "record_failed", step_id=str(step.id), attempt=attempt, error=str(exc)[:200]
                )
                if attempt == RECORD_ATTEMPTS:
                    return
                await asyncio.sleep(0.2 * attempt)
