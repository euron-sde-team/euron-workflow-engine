"""Aggregates for the dashboard. Every query is bounded by workspace and time window."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Integer, cast, func, literal_column, select

from workflow_engine.models import Execution, ExecutionStep, Workflow
from workflow_engine.models.enums import ExecutionStatus, StepStatus
from workflow_engine.repositories.base import Repository


class DashboardRepository(Repository):
    async def status_counts(self, workspace_id: uuid.UUID, since: datetime) -> dict[str, int]:
        result = await self.session.execute(
            select(Execution.status, func.count())
            .where(Execution.workspace_id == workspace_id, Execution.created_at >= since)
            .group_by(Execution.status)
        )
        return {str(row[0]): int(row[1]) for row in result.all()}

    async def volume(
        self, workspace_id: uuid.UUID, since: datetime, unit: str, timezone: str
    ) -> list[tuple[datetime, str, int]]:
        local = func.timezone(timezone, Execution.created_at)
        bucket = func.date_trunc(literal_column(f"'{unit}'"), local).label("bucket")
        result = await self.session.execute(
            select(bucket, Execution.status, func.count())
            .where(Execution.workspace_id == workspace_id, Execution.created_at >= since)
            .group_by(bucket, Execution.status)
            .order_by(bucket)
        )
        return [(row[0], str(row[1]), int(row[2])) for row in result.all()]

    async def durations(
        self, workspace_id: uuid.UUID, since: datetime
    ) -> tuple[int | None, int | None]:
        result = await self.session.execute(
            select(
                func.percentile_cont(0.5).within_group(Execution.duration_ms),
                func.percentile_cont(0.95).within_group(Execution.duration_ms),
            ).where(
                Execution.workspace_id == workspace_id,
                Execution.created_at >= since,
                Execution.status == ExecutionStatus.SUCCEEDED,
                Execution.duration_ms.is_not(None),
            )
        )
        p50, p95 = result.one()
        return (int(p50) if p50 is not None else None, int(p95) if p95 is not None else None)

    async def slowest(
        self, workspace_id: uuid.UUID, since: datetime, limit: int
    ) -> list[tuple[uuid.UUID, str, int, int, int]]:
        p95 = func.percentile_cont(0.95).within_group(Execution.duration_ms)
        result = await self.session.execute(
            select(
                Execution.workflow_id,
                Workflow.name,
                func.count(),
                cast(p95, Integer),
                cast(func.avg(Execution.duration_ms), Integer),
            )
            .join(Workflow, Workflow.id == Execution.workflow_id)
            .where(
                Execution.workspace_id == workspace_id,
                Execution.created_at >= since,
                Execution.status == ExecutionStatus.SUCCEEDED,
                Execution.duration_ms.is_not(None),
            )
            .group_by(Execution.workflow_id, Workflow.name)
            .having(func.count() >= 2)
            .order_by(p95.desc())
            .limit(limit)
        )
        return [(r[0], str(r[1]), int(r[2]), int(r[3] or 0), int(r[4] or 0)) for r in result.all()]

    async def busiest(
        self, workspace_id: uuid.UUID, since: datetime, limit: int
    ) -> list[tuple[uuid.UUID, str, int, int]]:
        failed = func.count().filter(Execution.status == ExecutionStatus.FAILED)
        result = await self.session.execute(
            select(Execution.workflow_id, Workflow.name, func.count(), failed)
            .join(Workflow, Workflow.id == Execution.workflow_id)
            .where(Execution.workspace_id == workspace_id, Execution.created_at >= since)
            .group_by(Execution.workflow_id, Workflow.name)
            .order_by(func.count().desc(), Workflow.name)
            .limit(limit)
        )
        return [(r[0], str(r[1]), int(r[2]), int(r[3])) for r in result.all()]

    async def recent_failures(
        self, workspace_id: uuid.UUID, limit: int
    ) -> list[tuple[Execution, str]]:
        result = await self.session.execute(
            select(Execution, Workflow.name)
            .join(Workflow, Workflow.id == Execution.workflow_id)
            .where(
                Execution.workspace_id == workspace_id, Execution.status == ExecutionStatus.FAILED
            )
            .order_by(Execution.finished_at.desc().nulls_last())
            .limit(limit)
        )
        return [(row[0], str(row[1])) for row in result.all()]

    async def queue(self, workspace_id: uuid.UUID, now: datetime) -> dict[str, int]:
        steps = await self.session.execute(
            select(
                func.count().filter(
                    ExecutionStep.status == StepStatus.QUEUED, ExecutionStep.available_at <= now
                ),
                func.count().filter(ExecutionStep.status == StepStatus.RUNNING),
                func.count().filter(ExecutionStep.status == StepStatus.WAITING),
            ).where(
                ExecutionStep.workspace_id == workspace_id,
                ExecutionStep.status.in_(
                    (StepStatus.QUEUED, StepStatus.RUNNING, StepStatus.WAITING)
                ),
            )
        )
        ready, running, waiting = steps.one()
        queued = await self.session.scalar(
            select(func.count())
            .select_from(Execution)
            .where(
                Execution.workspace_id == workspace_id, Execution.status == ExecutionStatus.QUEUED
            )
        )
        return {
            "executions_queued": int(queued or 0),
            "steps_ready": int(ready),
            "steps_running": int(running),
            "steps_waiting": int(waiting),
        }

    async def workflow_counts(self, workspace_id: uuid.UUID) -> tuple[int, int]:
        result = await self.session.execute(
            select(func.count(), func.count().filter(Workflow.active.is_(True))).where(
                Workflow.workspace_id == workspace_id
            )
        )
        total, active = result.one()
        return int(total), int(active)


def rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None
