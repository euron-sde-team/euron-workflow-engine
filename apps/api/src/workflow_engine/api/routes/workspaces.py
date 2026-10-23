"""Workspaces, members and the audit trail."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, status

from workflow_engine.api.deps import (
    ContainerDep,
    OwnerDep,
    PrincipalDep,
    SessionDep,
    UserDep,
    ViewerDep,
)
from workflow_engine.core.errors import ForbiddenError
from workflow_engine.models import Workspace
from workflow_engine.models.enums import Role
from workflow_engine.schemas.audit import AuditEventOut
from workflow_engine.schemas.auth import WorkspaceSummaryOut
from workflow_engine.schemas.common import CursorPage
from workflow_engine.schemas.workspaces import (
    MemberAdd,
    MemberAdded,
    MemberOut,
    MemberUpdate,
    WorkspaceCreate,
    WorkspaceOut,
    WorkspaceUpdate,
)
from workflow_engine.services.audit import AuditService
from workflow_engine.services.workspaces import WorkspaceService, workspace_settings

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])


def _out(workspace: Workspace, role: str) -> WorkspaceOut:
    return WorkspaceOut(
        id=workspace.id,
        slug=workspace.slug,
        name=workspace.name,
        description=workspace.description,
        settings=workspace_settings(workspace),
        role=role,
        created_at=workspace.created_at,
    )


@router.get("", summary="Workspaces you belong to")
async def list_workspaces(
    user: UserDep, container: ContainerDep, session: SessionDep
) -> list[WorkspaceSummaryOut]:
    summaries = await WorkspaceService(container, session).list_for(user)
    return [
        WorkspaceSummaryOut(
            id=s.workspace.id,
            slug=s.workspace.slug,
            name=s.workspace.name,
            role=s.role,
            workflow_count=s.workflow_count,
            active_workflow_count=s.active_workflow_count,
            member_count=s.member_count,
        )
        for s in summaries
    ]


@router.post("", summary="Create a workspace", status_code=status.HTTP_201_CREATED)
async def create_workspace(
    body: WorkspaceCreate,
    principal: PrincipalDep,
    user: UserDep,
    container: ContainerDep,
    session: SessionDep,
) -> WorkspaceOut:
    workspace = await WorkspaceService(container, session).create(
        principal, body.name, body.description
    )
    return _out(workspace, Role.OWNER.value)


@router.get("/{workspace}", summary="A workspace and your role in it")
async def get_workspace(ctx: ViewerDep) -> WorkspaceOut:
    return _out(ctx.workspace, ctx.role.value)


@router.patch("/{workspace}", summary="Rename, describe or change settings (owner)")
async def update_workspace(
    body: WorkspaceUpdate, ctx: OwnerDep, container: ContainerDep, session: SessionDep
) -> WorkspaceOut:
    updated = await WorkspaceService(container, session).update(
        ctx.workspace,
        ctx.principal,
        name=body.name,
        description=body.description,
        settings=body.settings,
    )
    return _out(updated, ctx.role.value)


@router.delete(
    "/{workspace}",
    summary="Delete a workspace with every workflow and execution in it (owner)",
    status_code=204,
)
async def delete_workspace(ctx: OwnerDep, container: ContainerDep, session: SessionDep) -> None:
    await WorkspaceService(container, session).delete(ctx.workspace)


@router.get("/{workspace}/members", summary="Members and their roles")
async def list_members(
    ctx: ViewerDep, container: ContainerDep, session: SessionDep
) -> list[MemberOut]:
    rows = await WorkspaceService(container, session).members(ctx.id)
    return [
        MemberOut(user_id=u.id, email=u.email, name=u.name, role=m.role, joined_at=m.created_at)
        for m, u in rows
    ]


@router.post(
    "/{workspace}/members", summary="Add a member (creates the account if needed)", status_code=201
)
async def add_member(
    body: MemberAdd, ctx: OwnerDep, container: ContainerDep, session: SessionDep
) -> MemberAdded:
    membership, user, password = await WorkspaceService(container, session).add_member(
        ctx.workspace, ctx.principal, body.email, body.name, Role(body.role)
    )
    return MemberAdded(
        member=MemberOut(
            user_id=user.id,
            email=user.email,
            name=user.name,
            role=membership.role,
            joined_at=membership.created_at,
        ),
        temporary_password=password,
    )


@router.patch("/{workspace}/members/{user_id}", summary="Change a member's role")
async def update_member(
    user_id: uuid.UUID,
    body: MemberUpdate,
    ctx: OwnerDep,
    container: ContainerDep,
    session: SessionDep,
) -> MemberOut:
    service = WorkspaceService(container, session)
    membership = await service.change_role(ctx.workspace, ctx.principal, user_id, Role(body.role))
    rows = {u.id: u for _, u in await service.members(ctx.id)}
    user = rows[user_id]
    return MemberOut(
        user_id=user.id,
        email=user.email,
        name=user.name,
        role=membership.role,
        joined_at=membership.created_at,
    )


@router.delete(
    "/{workspace}/members/{user_id}", summary="Remove a member (or leave)", status_code=204
)
async def remove_member(
    user_id: uuid.UUID, ctx: ViewerDep, container: ContainerDep, session: SessionDep
) -> None:
    leaving = ctx.principal.user_id == user_id
    if not leaving and ctx.role != Role.OWNER:
        raise ForbiddenError("Only owners can remove other members.")
    await WorkspaceService(container, session).remove_member(ctx.workspace, ctx.principal, user_id)


@router.get("/{workspace}/audit", summary="Every change in this workspace, newest first (owner)")
async def audit_log(
    ctx: OwnerDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    action: Annotated[str | None, Query(max_length=64)] = None,
    since: datetime | None = None,
) -> CursorPage[AuditEventOut]:
    return await AuditService(session).page(
        ctx.id, limit=limit, cursor=cursor, action=action, since=since
    )
