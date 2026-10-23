from __future__ import annotations

import uuid

from sqlalchemy import func, select

from workflow_engine.models import Credential
from workflow_engine.repositories.base import Repository


class CredentialRepository(Repository):
    async def get(self, workspace_id: uuid.UUID, credential_id: uuid.UUID) -> Credential | None:
        result = await self.session.execute(
            select(Credential).where(
                Credential.id == credential_id, Credential.workspace_id == workspace_id
            )
        )
        return result.scalar_one_or_none()

    async def by_name(self, workspace_id: uuid.UUID, name: str) -> Credential | None:
        result = await self.session.execute(
            select(Credential).where(
                Credential.workspace_id == workspace_id,
                func.lower(Credential.name) == name.lower(),
            )
        )
        return result.scalar_one_or_none()

    async def all(self, workspace_id: uuid.UUID) -> list[Credential]:
        result = await self.session.execute(
            select(Credential)
            .where(Credential.workspace_id == workspace_id)
            .order_by(Credential.name)
        )
        return list(result.scalars())

    async def types_by_id(self, workspace_id: uuid.UUID) -> dict[str, str]:
        result = await self.session.execute(
            select(Credential.id, Credential.type).where(Credential.workspace_id == workspace_id)
        )
        return {str(credential_id): kind for credential_id, kind in result.all()}

    async def add(self, credential: Credential) -> Credential:
        self.session.add(credential)
        await self.session.flush()
        return credential
