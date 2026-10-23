from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Integer, String, Text, and_, cast, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import ARRAY, distinct_on

from workflow_engine.models import Execution, Workflow, WorkflowTrigger, WorkflowVersion
from workflow_engine.models.enums import ExecutionStatus, VersionKind
from workflow_engine.repositories.base import Repository


@dataclass(frozen=True, slots=True)
class WorkflowStats:
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    last_execution_id: uuid.UUID | None = None
    last_status: str | None = None
    last_at: datetime | None = None


class WorkflowRepository(Repository):
    async def get(self, workspace_id: uuid.UUID, workflow_id: uuid.UUID) -> Workflow | None:
        result = await self.session.execute(
            select(Workflow).where(
                Workflow.id == workflow_id, Workflow.workspace_id == workspace_id
            )
        )
        return result.scalar_one_or_none()

    async def get_for_update(
        self, workspace_id: uuid.UUID, workflow_id: uuid.UUID
    ) -> Workflow | None:
        result = await self.session.execute(
            select(Workflow)
            .where(Workflow.id == workflow_id, Workflow.workspace_id == workspace_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def by_name(self, workspace_id: uuid.UUID, name: str) -> Workflow | None:
        result = await self.session.execute(
            select(Workflow).where(
                Workflow.workspace_id == workspace_id, func.lower(Workflow.name) == name.lower()
            )
        )
        return result.scalar_one_or_none()

    async def names_like(self, workspace_id: uuid.UUID, base: str) -> set[str]:
        result = await self.session.execute(
            select(Workflow.name).where(
                Workflow.workspace_id == workspace_id, Workflow.name.ilike(f"{base}%")
            )
        )
        return {name.lower() for name in result.scalars()}

    async def add(self, workflow: Workflow) -> Workflow:
        self.session.add(workflow)
        await self.session.flush()
        return workflow

    async def page(
        self,
        workspace_id: uuid.UUID,
        *,
        search: str | None,
        tag: str | None,
        active: bool | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Workflow], int]:
        conditions: list[Any] = [Workflow.workspace_id == workspace_id]
        if search:
            pattern = f"%{search.strip()}%"
            conditions.append(
                or_(Workflow.name.ilike(pattern), Workflow.description.ilike(pattern))
            )
        if tag:
            conditions.append(Workflow.tags.contains(cast([tag], ARRAY(Text))))
        if active is not None:
            conditions.append(Workflow.active.is_(active))
        total = int(
            await self.session.scalar(select(func.count()).select_from(Workflow).where(*conditions))
            or 0
        )
        result = await self.session.execute(
            select(Workflow)
            .where(*conditions)
            .order_by(Workflow.active.desc(), Workflow.updated_at.desc(), Workflow.id)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars()), total

    async def tags(self, workspace_id: uuid.UUID) -> list[str]:
        tag = func.unnest(Workflow.tags).label("tag")
        result = await self.session.execute(
            select(tag).where(Workflow.workspace_id == workspace_id).distinct().order_by("tag")
        )
        return [str(t) for t in result.scalars()]

    async def save_draft(
        self,
        workspace_id: uuid.UUID,
        workflow_id: uuid.UUID,
        *,
        definition: dict[str, Any],
        expected_revision: int,
        user_id: uuid.UUID | None,
    ) -> int | None:
        """Compare-and-set on the revision: None when someone else saved first."""
        result = await self.session.execute(
            update(Workflow)
            .where(
                Workflow.id == workflow_id,
                Workflow.workspace_id == workspace_id,
                Workflow.draft_revision == expected_revision,
            )
            .values(
                draft=definition,
                draft_revision=Workflow.draft_revision + 1,
                draft_updated_at=func.now(),
                draft_updated_by=user_id,
                updated_at=func.now(),
            )
            .returning(Workflow.draft_revision)
        )
        revision = result.scalar_one_or_none()
        return int(revision) if revision is not None else None

    async def stats(
        self, workflow_ids: Sequence[uuid.UUID], since: datetime
    ) -> dict[uuid.UUID, WorkflowStats]:
        """Counts since `since` and the latest execution, for a page of workflows: two queries."""
        if not workflow_ids:
            return {}
        counts = await self.session.execute(
            select(
                Execution.workflow_id,
                func.count(),
                func.count().filter(Execution.status == ExecutionStatus.SUCCEEDED),
                func.count().filter(Execution.status == ExecutionStatus.FAILED),
            )
            .where(Execution.workflow_id.in_(workflow_ids), Execution.created_at >= since)
            .group_by(Execution.workflow_id)
        )
        latest = await self.session.execute(
            select(Execution.workflow_id, Execution.id, Execution.status, Execution.created_at)
            .where(Execution.workflow_id.in_(workflow_ids))
            .ext(distinct_on(Execution.workflow_id))
            .order_by(Execution.workflow_id, Execution.created_at.desc())
        )
        stats: dict[uuid.UUID, WorkflowStats] = {}
        last = {row[0]: row[1:] for row in latest.all()}
        for workflow_id, total, succeeded, failed in counts.all():
            stats[workflow_id] = WorkflowStats(int(total), int(succeeded), int(failed))
        for workflow_id, (execution_id, status, at) in last.items():
            base = stats.get(workflow_id, WorkflowStats())
            stats[workflow_id] = WorkflowStats(
                base.total, base.succeeded, base.failed, execution_id, status, at
            )
        return stats

    async def referencing(self, workspace_id: uuid.UUID, needle: str) -> list[Workflow]:
        """Workflows whose draft or published definition mentions `needle` (a credential id)."""
        published = (
            select(WorkflowVersion.workflow_id)
            .where(
                WorkflowVersion.workspace_id == workspace_id,
                WorkflowVersion.kind == VersionKind.PUBLISHED,
                cast(WorkflowVersion.definition, String).contains(needle),
                WorkflowVersion.id == Workflow.published_version_id,
            )
            .exists()
        )
        result = await self.session.execute(
            select(Workflow)
            .where(
                Workflow.workspace_id == workspace_id,
                or_(cast(Workflow.draft, String).contains(needle), published),
            )
            .order_by(Workflow.name)
        )
        return list(result.scalars())


class VersionRepository(Repository):
    async def get(self, workspace_id: uuid.UUID, version_id: uuid.UUID) -> WorkflowVersion | None:
        result = await self.session.execute(
            select(WorkflowVersion).where(
                WorkflowVersion.id == version_id, WorkflowVersion.workspace_id == workspace_id
            )
        )
        return result.scalar_one_or_none()

    async def many(self, version_ids: Sequence[uuid.UUID]) -> list[WorkflowVersion]:
        if not version_ids:
            return []
        result = await self.session.execute(
            select(WorkflowVersion).where(WorkflowVersion.id.in_(version_ids))
        )
        return list(result.scalars())

    async def by_number(self, workflow_id: uuid.UUID, number: int) -> WorkflowVersion | None:
        result = await self.session.execute(
            select(WorkflowVersion).where(
                WorkflowVersion.workflow_id == workflow_id, WorkflowVersion.number == number
            )
        )
        return result.scalar_one_or_none()

    async def snapshot(self, workflow_id: uuid.UUID, checksum: str) -> WorkflowVersion | None:
        result = await self.session.execute(
            select(WorkflowVersion)
            .where(
                WorkflowVersion.workflow_id == workflow_id,
                WorkflowVersion.checksum == checksum,
            )
            .order_by(WorkflowVersion.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def next_number(self, workflow_id: uuid.UUID) -> int:
        current = await self.session.scalar(
            select(func.max(WorkflowVersion.number)).where(
                WorkflowVersion.workflow_id == workflow_id
            )
        )
        return int(current or 0) + 1

    async def add(self, version: WorkflowVersion) -> WorkflowVersion:
        self.session.add(version)
        await self.session.flush()
        return version

    async def published(self, workflow_id: uuid.UUID) -> list[WorkflowVersion]:
        result = await self.session.execute(
            select(WorkflowVersion)
            .where(
                WorkflowVersion.workflow_id == workflow_id,
                WorkflowVersion.kind == VersionKind.PUBLISHED,
            )
            .order_by(WorkflowVersion.number.desc())
        )
        return list(result.scalars())

    async def numbers(self, version_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int | None]:
        if not version_ids:
            return {}
        result = await self.session.execute(
            select(WorkflowVersion.id, cast(WorkflowVersion.number, Integer)).where(
                WorkflowVersion.id.in_(version_ids)
            )
        )
        return dict(result.tuples().all())


class TriggerRepository(Repository):
    async def for_workflow(self, workflow_id: uuid.UUID) -> list[WorkflowTrigger]:
        result = await self.session.execute(
            select(WorkflowTrigger).where(WorkflowTrigger.workflow_id == workflow_id)
        )
        return list(result.scalars())

    async def for_workflows(self, workflow_ids: Sequence[uuid.UUID]) -> list[WorkflowTrigger]:
        if not workflow_ids:
            return []
        result = await self.session.execute(
            select(WorkflowTrigger).where(WorkflowTrigger.workflow_id.in_(workflow_ids))
        )
        return list(result.scalars())

    async def replace(self, workflow_id: uuid.UUID, triggers: list[WorkflowTrigger]) -> None:
        await self.session.execute(
            delete(WorkflowTrigger).where(WorkflowTrigger.workflow_id == workflow_id)
        )
        self.session.add_all(triggers)
        await self.session.flush()

    async def clear(self, workflow_id: uuid.UUID) -> None:
        await self.session.execute(
            delete(WorkflowTrigger).where(WorkflowTrigger.workflow_id == workflow_id)
        )

    async def webhook_owner(self, workspace_id: uuid.UUID, path: str) -> WorkflowTrigger | None:
        result = await self.session.execute(
            select(WorkflowTrigger).where(
                WorkflowTrigger.workspace_id == workspace_id,
                WorkflowTrigger.kind == "webhook",
                WorkflowTrigger.webhook_path == path,
            )
        )
        return result.scalar_one_or_none()

    async def for_event(self, workspace_id: uuid.UUID, name: str) -> list[WorkflowTrigger]:
        """Event triggers for `name`: exact names, and prefixes such as `order.*`."""
        prefixes = [name]
        parts = name.split(".")
        prefixes.extend(".".join(parts[:i]) + ".*" for i in range(1, len(parts)))
        result = await self.session.execute(
            select(WorkflowTrigger).where(
                WorkflowTrigger.workspace_id == workspace_id,
                WorkflowTrigger.kind == "event",
                WorkflowTrigger.event_name.in_(prefixes),
            )
        )
        return list(result.scalars())

    async def due(self, now: datetime, limit: int) -> list[WorkflowTrigger]:
        """Schedules whose time has come, locked so a second scheduler skips them."""
        result = await self.session.execute(
            select(WorkflowTrigger)
            .where(
                WorkflowTrigger.kind.in_(("cron", "interval")),
                WorkflowTrigger.next_fire_at <= now,
            )
            .order_by(WorkflowTrigger.next_fire_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars())

    async def upcoming(
        self, workspace_id: uuid.UUID, limit: int
    ) -> list[tuple[WorkflowTrigger, str]]:
        result = await self.session.execute(
            select(WorkflowTrigger, Workflow.name)
            .join(Workflow, Workflow.id == WorkflowTrigger.workflow_id)
            .where(
                WorkflowTrigger.workspace_id == workspace_id,
                and_(WorkflowTrigger.kind.in_(("cron", "interval"))),
                WorkflowTrigger.next_fire_at.is_not(None),
            )
            .order_by(WorkflowTrigger.next_fire_at)
            .limit(limit)
        )
        return [(trigger, name) for trigger, name in result.all()]
