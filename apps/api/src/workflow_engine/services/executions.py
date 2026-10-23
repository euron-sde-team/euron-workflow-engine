"""Executions from the API's side: run, cancel, resume, retry, and read the history."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from workflow_engine.core import cursor as cursors
from workflow_engine.core.errors import ConflictError, NotFoundError, UnprocessableError
from workflow_engine.engine.definition import WorkflowDefinition, checksum
from workflow_engine.engine.validation import errors
from workflow_engine.models import (
    DeadLetter,
    Execution,
    ExecutionLog,
    ExecutionStep,
    WorkflowVersion,
)
from workflow_engine.models.enums import (
    DeadLetterStatus,
    ExecutionMode,
    ExecutionStatus,
    StepStatus,
    TriggerKind,
    VersionKind,
)
from workflow_engine.repositories.executions import (
    DeadLetterRepository,
    ExecutionFilters,
    ExecutionRepository,
    LogRepository,
    StepRepository,
)
from workflow_engine.repositories.workflows import VersionRepository, WorkflowRepository
from workflow_engine.services import audit
from workflow_engine.services.container import Container
from workflow_engine.services.engine import Engine, StartResult
from workflow_engine.services.principal import Principal
from workflow_engine.services.workflows import WorkflowService

MAX_STEPS_IN_DETAIL = 2000


@dataclass(frozen=True, slots=True)
class ExecutionDetail:
    execution: Execution
    workflow_name: str
    version_number: int | None
    steps: list[ExecutionStep]
    truncated: bool


def pick_trigger(definition: WorkflowDefinition, requested: str | None) -> str:
    triggers = [n for n in definition.nodes if n.type.startswith("trigger.")]
    if requested:
        if not any(n.id == requested for n in triggers):
            raise UnprocessableError(f"'{requested}' is not a trigger of this workflow.")
        return requested
    manual = [n for n in triggers if n.type == "trigger.manual"]
    chosen = (manual or triggers)[:1]
    if not chosen:
        raise UnprocessableError("This workflow has no trigger to run.")
    return chosen[0].id


def sample_payload(definition: WorkflowDefinition, trigger_id: str) -> Any:
    node = definition.node(trigger_id)
    return node.config.get("sample_payload", {}) if node else {}


class ExecutionService:
    def __init__(self, container: Container, session: AsyncSession) -> None:
        self.c = container
        self.session = session
        self.executions = ExecutionRepository(session)
        self.steps = StepRepository(session)
        self.letters = DeadLetterRepository(session)

    # Running -------------------------------------------------------------------------

    async def run(
        self,
        workspace_id: uuid.UUID,
        principal: Principal,
        workflow_id: uuid.UUID,
        *,
        payload: Any,
        use_draft: bool,
        trigger_node: str | None,
        idempotency_key: str | None,
    ) -> StartResult:
        workflows = WorkflowService(self.c, self.session)
        workflow = await workflows.get(workspace_id, workflow_id)
        versions = VersionRepository(self.session)
        if use_draft:
            definition = WorkflowDefinition.model_validate(workflow.draft)
            problems = errors(await workflows.issues(workspace_id, workflow.draft))
            if problems:
                raise UnprocessableError(
                    "Fix the problems in the workflow before running it.",
                    code="invalid_workflow",
                    details=[p.to_json() for p in problems],
                )
            digest = checksum(definition)
            version = await versions.snapshot(workflow.id, digest)
            if version is None:
                version = await versions.add(
                    WorkflowVersion(
                        workspace_id=workspace_id,
                        workflow_id=workflow.id,
                        kind=VersionKind.SNAPSHOT,
                        definition=definition.model_dump(mode="json"),
                        checksum=digest,
                        note="Test run of the draft",
                        created_by=principal.user_id,
                    )
                )
            mode = ExecutionMode.TEST
        else:
            if workflow.published_version_id is None:
                raise UnprocessableError(
                    "Publish the workflow first, or run the draft.", code="not_published"
                )
            found = await versions.get(workspace_id, workflow.published_version_id)
            if found is None:  # pragma: no cover - guarded by the foreign key
                raise NotFoundError("The published version is missing.")
            version = found
            definition = WorkflowDefinition.model_validate(version.definition)
            mode = ExecutionMode.MANUAL
        trigger_id = pick_trigger(definition, trigger_node)
        engine = Engine(self.c, self.session)
        result = await engine.start(
            workflow=workflow,
            version_id=version.id,
            trigger_node_id=trigger_id,
            payload=payload if payload is not None else sample_payload(definition, trigger_id),
            mode=mode,
            trigger_kind=TriggerKind.MANUAL,
            idempotency_key=f"run:{idempotency_key}" if idempotency_key else None,
            principal=principal,
        )
        await engine.commit()
        return result

    # Controlling ---------------------------------------------------------------------

    async def _locked(self, workspace_id: uuid.UUID, execution_id: uuid.UUID) -> Execution:
        found = await self.executions.get(workspace_id, execution_id)
        if found is None:
            raise NotFoundError("Execution not found.")
        locked = await self.executions.lock(execution_id)
        if locked is None:  # pragma: no cover - deleted between the two reads
            raise NotFoundError("Execution not found.")
        return locked

    async def cancel(
        self, workspace_id: uuid.UUID, principal: Principal, execution_id: uuid.UUID
    ) -> Execution:
        execution = await self._locked(workspace_id, execution_id)
        if ExecutionStatus(execution.status).is_terminal:
            raise ConflictError(
                f"The execution already {execution.status}.", code="already_finished"
            )
        engine = Engine(self.c, self.session)
        running = await self.steps.cancel_active(
            execution.id, {"code": "cancelled", "message": "Cancelled by a person."}
        )
        execution.status = ExecutionStatus.CANCELLED
        execution.error = {"code": "cancelled", "message": "Cancelled."}
        now = datetime.now(UTC)
        execution.finished_at = now
        started = execution.started_at or execution.created_at
        execution.duration_ms = int((now - started).total_seconds() * 1000)
        engine.admit_after_commit(execution.workflow_id)
        if running:
            engine.cancel_after_commit(execution.id)
        await audit.record(
            self.session,
            workspace_id=workspace_id,
            principal=principal,
            action="execution.cancelled",
            target_type="execution",
            target_id=execution.id,
        )
        await engine.commit()
        return execution

    async def resume(
        self, workspace_id: uuid.UUID, principal: Principal, execution_id: uuid.UUID
    ) -> Execution:
        execution = await self._locked(workspace_id, execution_id)
        if execution.status != ExecutionStatus.FAILED:
            raise ConflictError("Only failed executions can be resumed.", code="not_failed")
        steps = await self.steps.resumable(execution.id)
        if not steps:
            raise UnprocessableError(
                "Nothing is left to resume; retry the execution from the start instead.",
                code="nothing_to_resume",
            )
        engine = Engine(self.c, self.session)
        compiled = await engine.compiled(execution.version_id)
        now = datetime.now(UTC)
        names = []
        for step in steps:
            node = compiled.graph.node(step.node_id)
            policy = node.retry or self.c.registry[node.type].default_retry
            step.status = StepStatus.QUEUED
            step.max_attempts = step.attempt + policy.max_attempts
            step.available_at = now
            step.locked_by = None
            step.heartbeat_at = None
            step.finished_at = None
            step.error = None
            names.append(step.node_name)
        self.session.add(
            ExecutionLog(
                execution_id=execution.id,
                workspace_id=execution.workspace_id,
                level="info",
                message=f"Resumed from {', '.join(sorted(set(names)))}",
                data={"steps": [str(s.id) for s in steps]},
            )
        )
        workflow = await WorkflowRepository(self.session).get(workspace_id, execution.workflow_id)
        execution.status = ExecutionStatus.RUNNING
        execution.error = None
        execution.finished_at = None
        execution.duration_ms = None
        execution.resume_count += 1
        execution.deadline_at = now + timedelta(seconds=workflow.timeout_s if workflow else 3600)
        await self.letters.resolve_open(execution.id, DeadLetterStatus.RETRIED, principal.user_id)
        await audit.record(
            self.session,
            workspace_id=workspace_id,
            principal=principal,
            action="execution.resumed",
            target_type="execution",
            target_id=execution.id,
            details={"steps": len(steps)},
        )
        engine.wake_after_commit()
        await engine.commit()
        return execution

    async def retry(
        self, workspace_id: uuid.UUID, principal: Principal, execution_id: uuid.UUID
    ) -> StartResult:
        original = await self.executions.get(workspace_id, execution_id)
        if original is None:
            raise NotFoundError("Execution not found.")
        if not ExecutionStatus(original.status).is_terminal:
            raise ConflictError("The execution is still in progress.", code="not_finished")
        workflow = await WorkflowRepository(self.session).get(workspace_id, original.workflow_id)
        if workflow is None:  # pragma: no cover - cascades with the workflow
            raise NotFoundError("Workflow not found.")
        engine = Engine(self.c, self.session)
        result = await engine.start(
            workflow=workflow,
            version_id=original.version_id,
            trigger_node_id=original.trigger_node_id,
            payload=original.trigger_payload,
            mode=ExecutionMode(original.mode),
            trigger_kind=TriggerKind.RETRY,
            principal=principal,
            retry_of_id=original.id,
        )
        await self.letters.resolve_open(original.id, DeadLetterStatus.RETRIED, principal.user_id)
        await audit.record(
            self.session,
            workspace_id=workspace_id,
            principal=principal,
            action="execution.retried",
            target_type="execution",
            target_id=original.id,
            details={"new_execution": str(result.execution.id)},
        )
        await engine.commit()
        return result

    # Reading -------------------------------------------------------------------------

    async def page(
        self, workspace_id: uuid.UUID, filters: ExecutionFilters, *, limit: int, cursor: str | None
    ) -> tuple[list[tuple[Execution, str]], str | None]:
        after = cursors.decode_uuid(cursor) if cursor else None
        rows = await self.executions.page(workspace_id, filters, limit=limit + 1, after=after)
        next_cursor = (
            cursors.encode(rows[limit - 1][0].created_at, rows[limit - 1][0].id)
            if len(rows) > limit
            else None
        )
        return rows[:limit], next_cursor

    async def detail(self, workspace_id: uuid.UUID, execution_id: uuid.UUID) -> ExecutionDetail:
        execution = await self.executions.get(workspace_id, execution_id)
        if execution is None:
            raise NotFoundError("Execution not found.")
        workflow = await WorkflowRepository(self.session).get(workspace_id, execution.workflow_id)
        version = await VersionRepository(self.session).get(workspace_id, execution.version_id)
        steps = await self.steps.for_execution(execution.id)
        return ExecutionDetail(
            execution=execution,
            workflow_name=workflow.name if workflow else "",
            version_number=version.number if version else None,
            steps=steps[:MAX_STEPS_IN_DETAIL],
            truncated=len(steps) > MAX_STEPS_IN_DETAIL,
        )

    async def version(self, workspace_id: uuid.UUID, execution_id: uuid.UUID) -> WorkflowVersion:
        """The exact version an execution ran, draft snapshots included."""
        execution = await self.executions.get(workspace_id, execution_id)
        if execution is None:
            raise NotFoundError("Execution not found.")
        version = await VersionRepository(self.session).get(workspace_id, execution.version_id)
        if version is None:
            raise NotFoundError("The version this execution ran is missing.")
        return version

    async def step(
        self, workspace_id: uuid.UUID, execution_id: uuid.UUID, step_id: uuid.UUID
    ) -> ExecutionStep:
        step = await self.session.get(ExecutionStep, step_id)
        if step is None or step.workspace_id != workspace_id or step.execution_id != execution_id:
            raise NotFoundError("Step not found.")
        return step

    async def logs(
        self,
        workspace_id: uuid.UUID,
        execution_id: uuid.UUID,
        *,
        step_id: uuid.UUID | None,
        after_id: int | None,
        limit: int,
    ) -> list[ExecutionLog]:
        if await self.executions.get(workspace_id, execution_id) is None:
            raise NotFoundError("Execution not found.")
        return await LogRepository(self.session).page(
            execution_id, step_id=step_id, after_id=after_id, limit=limit
        )

    # Dead letters ----------------------------------------------------------------------

    async def dead_letters(
        self, workspace_id: uuid.UUID, *, status: str | None, limit: int, cursor: str | None
    ) -> tuple[list[tuple[DeadLetter, str]], str | None]:
        after = cursors.decode_uuid(cursor) if cursor else None
        rows = await self.letters.page(workspace_id, status=status, limit=limit + 1, after=after)
        next_cursor = (
            cursors.encode(rows[limit - 1][0].created_at, rows[limit - 1][0].id)
            if len(rows) > limit
            else None
        )
        return rows[:limit], next_cursor

    async def discard(
        self, workspace_id: uuid.UUID, principal: Principal, letter_id: uuid.UUID
    ) -> DeadLetter:
        letter = await self.letters.get(workspace_id, letter_id)
        if letter is None:
            raise NotFoundError("Dead letter not found.")
        if letter.status != DeadLetterStatus.OPEN:
            raise ConflictError("This dead letter was already handled.", code="already_resolved")
        letter.status = DeadLetterStatus.DISCARDED
        letter.resolved_at = datetime.now(UTC)
        letter.resolved_by = principal.user_id
        await audit.record(
            self.session,
            workspace_id=workspace_id,
            principal=principal,
            action="dead_letter.discarded",
            target_type="dead_letter",
            target_id=letter.id,
            details={"execution_id": str(letter.execution_id), "node": letter.node_name},
        )
        await self.session.commit()
        return letter

    async def letter(self, workspace_id: uuid.UUID, letter_id: uuid.UUID) -> DeadLetter:
        letter = await self.letters.get(workspace_id, letter_id)
        if letter is None:
            raise NotFoundError("Dead letter not found.")
        return letter
