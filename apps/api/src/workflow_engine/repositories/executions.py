"""Executions, steps (the queue), logs and dead letters.

Every statement that hands out or changes queue state is written here, so the guarded
patterns are easy to audit: claims use `FOR UPDATE SKIP LOCKED`, and every later write to a
step names the worker that holds it.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import distinct_on, insert

from workflow_engine.models import (
    DeadLetter,
    Event,
    Execution,
    ExecutionLog,
    ExecutionStep,
    Workflow,
)
from workflow_engine.models.enums import (
    ACTIVE_STEP_STATUSES,
    DeadLetterStatus,
    ExecutionStatus,
    StepStatus,
)
from workflow_engine.repositories.base import Repository


@dataclass(frozen=True, slots=True)
class ActiveCounts:
    queued: int = 0
    running: int = 0
    waiting: int = 0


@dataclass(frozen=True, slots=True)
class ExecutionFilters:
    workflow_id: uuid.UUID | None = None
    status: str | None = None
    trigger_kind: str | None = None
    mode: str | None = None
    since: datetime | None = None
    until: datetime | None = None


class ExecutionRepository(Repository):
    async def get(self, workspace_id: uuid.UUID, execution_id: uuid.UUID) -> Execution | None:
        result = await self.session.execute(
            select(Execution).where(
                Execution.id == execution_id, Execution.workspace_id == workspace_id
            )
        )
        return result.scalar_one_or_none()

    async def lock(self, execution_id: uuid.UUID, *, skip_locked: bool = False) -> Execution | None:
        """The execution row, locked: completions of one execution are serialized."""
        result = await self.session.execute(
            select(Execution)
            .where(Execution.id == execution_id)
            .with_for_update(skip_locked=skip_locked)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def insert(self, values: dict[str, Any], *, idempotent: bool) -> uuid.UUID | None:
        """Insert; with an idempotency key, None means the key was already used."""
        statement = insert(Execution).values(**values)
        if idempotent:
            statement = statement.on_conflict_do_nothing(
                index_elements=[Execution.workflow_id, Execution.idempotency_key],
                index_where=text("idempotency_key IS NOT NULL"),
            )
        result = await self.session.execute(statement.returning(Execution.id))
        return result.scalar_one_or_none()

    async def by_key(self, workflow_id: uuid.UUID, key: str) -> Execution | None:
        result = await self.session.execute(
            select(Execution).where(
                Execution.workflow_id == workflow_id, Execution.idempotency_key == key
            )
        )
        return result.scalar_one_or_none()

    async def lock_workflow(self, workflow_id: uuid.UUID) -> Workflow | None:
        result = await self.session.execute(
            select(Workflow).where(Workflow.id == workflow_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def running_count(self, workflow_id: uuid.UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(Execution)
                .where(
                    Execution.workflow_id == workflow_id,
                    Execution.status == ExecutionStatus.RUNNING,
                )
            )
            or 0
        )

    async def in_progress_count(self, workflow_id: uuid.UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(Execution)
                .where(
                    Execution.workflow_id == workflow_id,
                    Execution.status.in_((ExecutionStatus.QUEUED, ExecutionStatus.RUNNING)),
                )
            )
            or 0
        )

    async def queued_for_admission(self, workflow_id: uuid.UUID, limit: int) -> list[Execution]:
        result = await self.session.execute(
            select(Execution)
            .where(Execution.workflow_id == workflow_id, Execution.status == ExecutionStatus.QUEUED)
            .order_by(Execution.created_at, Execution.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars())

    async def workflows_with_queued(self, limit: int) -> list[uuid.UUID]:
        result = await self.session.execute(
            select(Execution.workflow_id)
            .where(Execution.status == ExecutionStatus.QUEUED)
            .group_by(Execution.workflow_id)
            .order_by(func.min(Execution.created_at))
            .limit(limit)
        )
        return list(result.scalars())

    async def past_deadline(self, now: datetime, limit: int) -> list[uuid.UUID]:
        result = await self.session.execute(
            select(Execution.id)
            .where(
                Execution.status.in_((ExecutionStatus.RUNNING, ExecutionStatus.WAITING)),
                Execution.deadline_at < now,
            )
            .limit(limit)
        )
        return list(result.scalars())

    async def page(
        self,
        workspace_id: uuid.UUID,
        filters: ExecutionFilters,
        *,
        limit: int,
        after: tuple[datetime, uuid.UUID] | None,
    ) -> list[tuple[Execution, str]]:
        query = (
            select(Execution, Workflow.name)
            .join(Workflow, Workflow.id == Execution.workflow_id)
            .where(Execution.workspace_id == workspace_id)
        )
        if filters.workflow_id:
            query = query.where(Execution.workflow_id == filters.workflow_id)
        if filters.status:
            query = query.where(Execution.status == filters.status)
        if filters.trigger_kind:
            query = query.where(Execution.trigger_kind == filters.trigger_kind)
        if filters.mode:
            query = query.where(Execution.mode == filters.mode)
        if filters.since:
            query = query.where(Execution.created_at >= filters.since)
        if filters.until:
            query = query.where(Execution.created_at < filters.until)
        if after is not None:
            query = query.where(tuple_(Execution.created_at, Execution.id) < tuple_(*after))
        result = await self.session.execute(
            query.order_by(Execution.created_at.desc(), Execution.id.desc()).limit(limit)
        )
        return [(execution, name) for execution, name in result.all()]

    async def prune(self, workspace_id: uuid.UUID, cutoff: datetime, limit: int) -> int:
        doomed = (
            select(Execution.id)
            .where(Execution.workspace_id == workspace_id, Execution.finished_at < cutoff)
            .limit(limit)
            .scalar_subquery()
        )
        result = await self.session.execute(
            delete(Execution).where(Execution.id.in_(doomed)).returning(Execution.id)
        )
        return len(result.scalars().all())

    async def prune_events(self, workspace_id: uuid.UUID, cutoff: datetime, limit: int) -> int:
        doomed = (
            select(Event.id)
            .where(Event.workspace_id == workspace_id, Event.created_at < cutoff)
            .limit(limit)
            .scalar_subquery()
        )
        result = await self.session.execute(
            delete(Event).where(Event.id.in_(doomed)).returning(Event.id)
        )
        return len(result.scalars().all())

    async def status_counts(self) -> dict[str, int]:
        result = await self.session.execute(
            select(Execution.status, func.count())
            .where(
                Execution.status.in_(
                    (ExecutionStatus.QUEUED, ExecutionStatus.RUNNING, ExecutionStatus.WAITING)
                )
            )
            .group_by(Execution.status)
        )
        return {status: int(count) for status, count in result.all()}


class StepRepository(Repository):
    async def claim(self, worker_id: str, limit: int) -> list[ExecutionStep]:
        candidates = (
            select(ExecutionStep.id)
            .where(
                ExecutionStep.status == StepStatus.QUEUED,
                ExecutionStep.available_at <= func.now(),
            )
            .order_by(ExecutionStep.available_at, ExecutionStep.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        result = await self.session.execute(
            update(ExecutionStep)
            .where(ExecutionStep.id.in_(candidates))
            .values(
                status=StepStatus.RUNNING,
                locked_by=worker_id,
                locked_at=func.now(),
                heartbeat_at=func.now(),
                started_at=func.now(),
                attempt=ExecutionStep.attempt + 1,
                updated_at=func.now(),
            )
            .returning(ExecutionStep)
            .execution_options(synchronize_session=False)
        )
        return list(result.scalars())

    async def heartbeat(self, worker_id: str, step_ids: Sequence[uuid.UUID]) -> set[uuid.UUID]:
        """Refresh the heartbeat of the steps this worker still holds; returns those ids."""
        if not step_ids:
            return set()
        result = await self.session.execute(
            update(ExecutionStep)
            .where(
                ExecutionStep.id.in_(step_ids),
                ExecutionStep.locked_by == worker_id,
                ExecutionStep.status == StepStatus.RUNNING,
            )
            .values(heartbeat_at=func.now())
            .returning(ExecutionStep.id)
            .execution_options(synchronize_session=False)
        )
        return set(result.scalars())

    async def held(self, step_id: uuid.UUID, worker_id: str) -> ExecutionStep | None:
        """The step if this worker still holds it (the guard for every completion)."""
        result = await self.session.execute(
            select(ExecutionStep)
            .where(
                ExecutionStep.id == step_id,
                ExecutionStep.locked_by == worker_id,
                ExecutionStep.status == StepStatus.RUNNING,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def lock(self, step_id: uuid.UUID) -> ExecutionStep | None:
        result = await self.session.execute(
            select(ExecutionStep)
            .where(ExecutionStep.id == step_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def active_counts(self, execution_id: uuid.UUID) -> ActiveCounts:
        result = await self.session.execute(
            select(ExecutionStep.status, func.count())
            .where(
                ExecutionStep.execution_id == execution_id,
                ExecutionStep.status.in_(ACTIVE_STEP_STATUSES),
            )
            .group_by(ExecutionStep.status)
        )
        counts = {status: int(count) for status, count in result.all()}
        return ActiveCounts(
            counts.get(StepStatus.QUEUED, 0),
            counts.get(StepStatus.RUNNING, 0),
            counts.get(StepStatus.WAITING, 0),
        )

    async def latest_outputs(
        self, execution_id: uuid.UUID, node_ids: Sequence[str]
    ) -> dict[str, Any]:
        """The newest successful output of each node in `node_ids`: one query."""
        if not node_ids:
            return {}
        result = await self.session.execute(
            select(ExecutionStep.node_id, ExecutionStep.output)
            .where(
                ExecutionStep.execution_id == execution_id,
                ExecutionStep.node_id.in_(node_ids),
                ExecutionStep.status == StepStatus.SUCCEEDED,
            )
            .ext(distinct_on(ExecutionStep.node_id))
            .order_by(ExecutionStep.node_id, ExecutionStep.finished_at.desc())
        )
        return {str(row[0]): row[1] for row in result.all()}

    async def final_output(self, execution_id: uuid.UUID, leaves: Sequence[str]) -> Any:
        """The output of the most recently finished leaf step (or any step if no leaf ran)."""
        query = (
            select(ExecutionStep.output)
            .where(
                ExecutionStep.execution_id == execution_id,
                ExecutionStep.status == StepStatus.SUCCEEDED,
            )
            .order_by(ExecutionStep.finished_at.desc(), ExecutionStep.id.desc())
            .limit(1)
        )
        if leaves:
            leaf = await self.session.scalar(query.where(ExecutionStep.node_id.in_(leaves)))
            if leaf is not None:
                return leaf
        return await self.session.scalar(query)

    async def for_execution(self, execution_id: uuid.UUID) -> list[ExecutionStep]:
        result = await self.session.execute(
            select(ExecutionStep)
            .where(ExecutionStep.execution_id == execution_id)
            .order_by(ExecutionStep.created_at, ExecutionStep.id)
        )
        return list(result.scalars())

    async def cancel_active(
        self, execution_id: uuid.UUID, error: dict[str, Any], *, except_id: uuid.UUID | None = None
    ) -> list[uuid.UUID]:
        """Cancel every queued, waiting or running step; returns the running ones."""
        conditions = [
            ExecutionStep.execution_id == execution_id,
            ExecutionStep.status.in_(ACTIVE_STEP_STATUSES),
        ]
        if except_id is not None:
            conditions.append(ExecutionStep.id != except_id)
        result = await self.session.execute(
            update(ExecutionStep)
            .where(*conditions)
            .values(
                status=StepStatus.CANCELLED,
                error=error,
                finished_at=func.now(),
                updated_at=func.now(),
            )
            .returning(ExecutionStep.id, ExecutionStep.locked_by)
            .execution_options(synchronize_session=False)
        )
        return [step_id for step_id, locked_by in result.all() if locked_by]

    async def resumable(self, execution_id: uuid.UUID) -> list[ExecutionStep]:
        """Failed steps, and the steps cancelled because of the failure."""
        result = await self.session.execute(
            select(ExecutionStep)
            .where(
                ExecutionStep.execution_id == execution_id,
                (ExecutionStep.status == StepStatus.FAILED)
                | (
                    (ExecutionStep.status == StepStatus.CANCELLED)
                    & (ExecutionStep.error["code"].astext == "upstream_failure")
                ),
            )
            .with_for_update()
        )
        return list(result.scalars())

    async def stale(self, cutoff: datetime, limit: int) -> list[tuple[uuid.UUID, uuid.UUID]]:
        result = await self.session.execute(
            select(ExecutionStep.id, ExecutionStep.execution_id)
            .where(ExecutionStep.status == StepStatus.RUNNING, ExecutionStep.heartbeat_at < cutoff)
            .limit(limit)
        )
        return [(step_id, execution_id) for step_id, execution_id in result.all()]

    async def due_waiting(self, now: datetime, limit: int) -> list[tuple[uuid.UUID, uuid.UUID]]:
        result = await self.session.execute(
            select(ExecutionStep.id, ExecutionStep.execution_id)
            .where(ExecutionStep.status == StepStatus.WAITING, ExecutionStep.available_at <= now)
            .order_by(ExecutionStep.available_at)
            .limit(limit)
        )
        return [(step_id, execution_id) for step_id, execution_id in result.all()]

    async def status_counts(self) -> dict[str, int]:
        result = await self.session.execute(
            select(ExecutionStep.status, func.count())
            .where(ExecutionStep.status.in_(ACTIVE_STEP_STATUSES))
            .group_by(ExecutionStep.status)
        )
        return {status: int(count) for status, count in result.all()}

    async def ready_count(self, now: datetime) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(ExecutionStep)
                .where(ExecutionStep.status == StepStatus.QUEUED, ExecutionStep.available_at <= now)
            )
            or 0
        )


class LogRepository(Repository):
    def add_many(self, logs: Sequence[ExecutionLog]) -> None:
        self.session.add_all(logs)

    async def page(
        self,
        execution_id: uuid.UUID,
        *,
        step_id: uuid.UUID | None,
        after_id: int | None,
        limit: int,
    ) -> list[ExecutionLog]:
        query = select(ExecutionLog).where(ExecutionLog.execution_id == execution_id)
        if step_id is not None:
            query = query.where(ExecutionLog.step_id == step_id)
        if after_id is not None:
            query = query.where(ExecutionLog.id > after_id)
        result = await self.session.execute(query.order_by(ExecutionLog.id).limit(limit))
        return list(result.scalars())


class DeadLetterRepository(Repository):
    def add(self, letter: DeadLetter) -> None:
        self.session.add(letter)

    async def get(self, workspace_id: uuid.UUID, letter_id: uuid.UUID) -> DeadLetter | None:
        result = await self.session.execute(
            select(DeadLetter).where(
                DeadLetter.id == letter_id, DeadLetter.workspace_id == workspace_id
            )
        )
        return result.scalar_one_or_none()

    async def resolve_open(
        self, execution_id: uuid.UUID, status: DeadLetterStatus, user_id: uuid.UUID | None
    ) -> int:
        result = await self.session.execute(
            update(DeadLetter)
            .where(
                DeadLetter.execution_id == execution_id, DeadLetter.status == DeadLetterStatus.OPEN
            )
            .values(status=status, resolved_at=func.now(), resolved_by=user_id)
            .returning(DeadLetter.id)
            .execution_options(synchronize_session=False)
        )
        return len(result.scalars().all())

    async def page(
        self,
        workspace_id: uuid.UUID,
        *,
        status: str | None,
        limit: int,
        after: tuple[datetime, uuid.UUID] | None,
    ) -> list[tuple[DeadLetter, str]]:
        query = (
            select(DeadLetter, Workflow.name)
            .join(Workflow, Workflow.id == DeadLetter.workflow_id)
            .where(DeadLetter.workspace_id == workspace_id)
        )
        if status:
            query = query.where(DeadLetter.status == status)
        if after is not None:
            query = query.where(tuple_(DeadLetter.created_at, DeadLetter.id) < tuple_(*after))
        result = await self.session.execute(
            query.order_by(DeadLetter.created_at.desc(), DeadLetter.id.desc()).limit(limit)
        )
        return [(letter, name) for letter, name in result.all()]

    async def open_count(self, workspace_id: uuid.UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(DeadLetter)
                .where(
                    DeadLetter.workspace_id == workspace_id,
                    DeadLetter.status == DeadLetterStatus.OPEN,
                )
            )
            or 0
        )
