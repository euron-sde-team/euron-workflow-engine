"""Workspaces, membership and access resolution."""

from __future__ import annotations

import re
import secrets
import unicodedata
import uuid

import anyio
from sqlalchemy.ext.asyncio import AsyncSession

from workflow_engine.core.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnprocessableError,
)
from workflow_engine.core.security import hash_password
from workflow_engine.models import Membership, User, Workspace
from workflow_engine.models.enums import Role
from workflow_engine.repositories.users import UserRepository
from workflow_engine.repositories.workspaces import WorkspaceRepository, WorkspaceSummary
from workflow_engine.schemas.workspaces import WorkspaceSettings
from workflow_engine.services import audit
from workflow_engine.services.auth import temporary_password
from workflow_engine.services.container import Container
from workflow_engine.services.principal import Principal


def slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return slug[:48].strip("-") or "workspace"


def workspace_settings(workspace: Workspace) -> WorkspaceSettings:
    return WorkspaceSettings.model_validate(workspace.settings or {})


class WorkspaceService:
    def __init__(self, container: Container, session: AsyncSession) -> None:
        self.c = container
        self.session = session
        self.workspaces = WorkspaceRepository(session)
        self.users = UserRepository(session)

    async def resolve(self, principal: Principal, ref: str) -> tuple[Workspace, Role]:
        """The workspace and the caller's role in it. Non-members get 404, not 403."""
        workspace = await self._by_ref(ref)
        if workspace is None:
            raise NotFoundError("Workspace not found.")
        if principal.api_key is not None:
            if principal.api_key.workspace_id != workspace.id:
                raise NotFoundError("Workspace not found.")
            return workspace, Role(principal.api_key.role)
        if principal.user is None:
            raise NotFoundError("Workspace not found.")
        membership = await self.workspaces.membership(workspace.id, principal.user.id)
        if membership is None:
            raise NotFoundError("Workspace not found.")
        return workspace, Role(membership.role)

    async def _by_ref(self, ref: str) -> Workspace | None:
        try:
            return await self.workspaces.get(uuid.UUID(ref))
        except ValueError:
            return await self.workspaces.by_slug(ref.lower())

    async def list_for(self, user: User) -> list[WorkspaceSummary]:
        return await self.workspaces.for_user(user.id)

    async def create(self, principal: Principal, name: str, description: str = "") -> Workspace:
        if principal.user is None:
            raise ForbiddenError("Only people can create workspaces.")
        base = slugify(name)
        slug = base
        while await self.workspaces.slug_taken(slug):
            slug = f"{base}-{secrets.token_hex(2)}"
        workspace = await self.workspaces.add(
            Workspace(
                slug=slug,
                name=name.strip(),
                description=description.strip(),
                settings=WorkspaceSettings(
                    retention_days=self.c.settings.default_retention_days
                ).model_dump(),
                created_by=principal.user.id,
            )
        )
        await self.workspaces.add_member(workspace.id, principal.user.id, Role.OWNER)
        await audit.record(
            self.session,
            workspace_id=workspace.id,
            principal=principal,
            action="workspace.created",
            target_type="workspace",
            target_id=workspace.id,
            details={"name": workspace.name},
        )
        await self.session.commit()
        return workspace

    async def update(
        self,
        workspace: Workspace,
        principal: Principal,
        *,
        name: str | None,
        description: str | None,
        settings: WorkspaceSettings | None,
    ) -> Workspace:
        changed: dict[str, object] = {}
        if name is not None and name.strip() != workspace.name:
            workspace.name = name.strip()
            changed["name"] = workspace.name
        if description is not None and description.strip() != workspace.description:
            workspace.description = description.strip()
            changed["description"] = True
        if settings is not None and settings.model_dump() != workspace.settings:
            workspace.settings = settings.model_dump()
            changed["settings"] = workspace.settings
        if changed:
            await audit.record(
                self.session,
                workspace_id=workspace.id,
                principal=principal,
                action="workspace.updated",
                target_type="workspace",
                target_id=workspace.id,
                details=changed,
            )
            await self.session.commit()
        return workspace

    async def delete(self, workspace: Workspace) -> None:
        # Every workflow, execution, credential and event cascades with the workspace.
        await self.session.delete(workspace)
        await self.session.commit()

    async def members(self, workspace_id: uuid.UUID) -> list[tuple[Membership, User]]:
        return await self.workspaces.members(workspace_id)

    async def add_member(
        self, workspace: Workspace, principal: Principal, email: str, name: str | None, role: Role
    ) -> tuple[Membership, User, str | None]:
        user = await self.users.by_email(email)
        password: str | None = None
        if user is None:
            password = temporary_password()
            user = await self.users.add(
                User(
                    email=email.strip().lower(),
                    name=(name or email.split("@")[0]).strip()[:120],
                    password_hash=await anyio.to_thread.run_sync(hash_password, password),
                )
            )
        elif await self.workspaces.membership(workspace.id, user.id):
            raise ConflictError("That person is already a member.")
        membership = await self.workspaces.add_member(workspace.id, user.id, role)
        await audit.record(
            self.session,
            workspace_id=workspace.id,
            principal=principal,
            action="member.added",
            target_type="user",
            target_id=user.id,
            details={
                "email": user.email,
                "role": role.value,
                "account_created": password is not None,
            },
        )
        await self.session.commit()
        return membership, user, password

    async def change_role(
        self, workspace: Workspace, principal: Principal, user_id: uuid.UUID, role: Role
    ) -> Membership:
        membership = await self.workspaces.membership(workspace.id, user_id)
        if membership is None:
            raise NotFoundError("That person is not a member.")
        if membership.role == Role.OWNER and role != Role.OWNER:
            await self._keep_an_owner(workspace.id)
        membership.role = role.value
        await audit.record(
            self.session,
            workspace_id=workspace.id,
            principal=principal,
            action="member.role_changed",
            target_type="user",
            target_id=user_id,
            details={"role": role.value},
        )
        await self.session.commit()
        return membership

    async def remove_member(
        self, workspace: Workspace, principal: Principal, user_id: uuid.UUID
    ) -> None:
        membership = await self.workspaces.membership(workspace.id, user_id)
        if membership is None:
            raise NotFoundError("That person is not a member.")
        if membership.role == Role.OWNER:
            await self._keep_an_owner(workspace.id)
        await self.session.delete(membership)
        await audit.record(
            self.session,
            workspace_id=workspace.id,
            principal=principal,
            action="member.removed",
            target_type="user",
            target_id=user_id,
        )
        await self.session.commit()

    async def _keep_an_owner(self, workspace_id: uuid.UUID) -> None:
        if await self.workspaces.owner_count(workspace_id) <= 1:
            raise UnprocessableError("A workspace needs at least one owner.", code="last_owner")


def require_role(role: Role, required: Role) -> None:
    if not role.allows(required):
        raise ForbiddenError(f"This needs the {required.value} role in this workspace.")
