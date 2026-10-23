from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from workflow_engine.models import Membership, User, Workflow, Workspace
from workflow_engine.models.enums import Role
from workflow_engine.repositories.base import Repository


@dataclass(frozen=True, slots=True)
class WorkspaceSummary:
    workspace: Workspace
    role: str
    workflow_count: int
    active_workflow_count: int
    member_count: int


class WorkspaceRepository(Repository):
    async def get(self, workspace_id: uuid.UUID) -> Workspace | None:
        return await self.session.get(Workspace, workspace_id)

    async def by_slug(self, slug: str) -> Workspace | None:
        result = await self.session.execute(select(Workspace).where(Workspace.slug == slug))
        return result.scalar_one_or_none()

    async def slug_taken(self, slug: str) -> bool:
        return bool(await self.session.scalar(select(func.count()).where(Workspace.slug == slug)))

    async def add(self, workspace: Workspace) -> Workspace:
        self.session.add(workspace)
        await self.session.flush()
        return workspace

    async def membership(self, workspace_id: uuid.UUID, user_id: uuid.UUID) -> Membership | None:
        return await self.session.get(Membership, (workspace_id, user_id))

    async def for_user(self, user_id: uuid.UUID) -> list[WorkspaceSummary]:
        others = aliased(Membership)
        workflows = (
            select(func.count())
            .select_from(Workflow)
            .where(Workflow.workspace_id == Workspace.id)
            .correlate(Workspace)
            .scalar_subquery()
        )
        active = (
            select(func.count())
            .select_from(Workflow)
            .where(Workflow.workspace_id == Workspace.id, Workflow.active.is_(True))
            .correlate(Workspace)
            .scalar_subquery()
        )
        members = (
            select(func.count())
            .select_from(others)
            .where(others.workspace_id == Workspace.id)
            .correlate(Workspace)
            .scalar_subquery()
        )
        result = await self.session.execute(
            select(Workspace, Membership.role, workflows, active, members)
            .join(Membership, Membership.workspace_id == Workspace.id)
            .where(Membership.user_id == user_id)
            .order_by(Workspace.name)
        )
        return [
            WorkspaceSummary(w, role, total, running, people)
            for w, role, total, running, people in result.all()
        ]

    async def members(self, workspace_id: uuid.UUID) -> list[tuple[Membership, User]]:
        result = await self.session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.workspace_id == workspace_id)
            .order_by(Membership.created_at)
        )
        return [(m, u) for m, u in result.all()]

    async def owner_count(self, workspace_id: uuid.UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count()).where(
                    Membership.workspace_id == workspace_id, Membership.role == Role.OWNER
                )
            )
            or 0
        )

    async def add_member(
        self, workspace_id: uuid.UUID, user_id: uuid.UUID, role: Role
    ) -> Membership:
        membership = Membership(workspace_id=workspace_id, user_id=user_id, role=role.value)
        self.session.add(membership)
        await self.session.flush()
        return membership

    async def all_ids(self) -> list[tuple[uuid.UUID, int]]:
        """Every workspace with its retention window, for the pruning sweep."""
        result = await self.session.execute(select(Workspace.id, Workspace.settings))
        return [
            (workspace_id, int((settings or {}).get("retention_days", 30)))
            for workspace_id, settings in result.all()
        ]
