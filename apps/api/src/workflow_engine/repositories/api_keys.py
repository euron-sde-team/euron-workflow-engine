from __future__ import annotations

import uuid

from sqlalchemy import select

from workflow_engine.models import ApiKey
from workflow_engine.repositories.base import Repository


class ApiKeyRepository(Repository):
    async def by_prefix(self, prefix: str) -> ApiKey | None:
        result = await self.session.execute(select(ApiKey).where(ApiKey.prefix == prefix))
        return result.scalar_one_or_none()

    async def get(self, workspace_id: uuid.UUID, key_id: uuid.UUID) -> ApiKey | None:
        result = await self.session.execute(
            select(ApiKey).where(ApiKey.id == key_id, ApiKey.workspace_id == workspace_id)
        )
        return result.scalar_one_or_none()

    async def for_workspace(self, workspace_id: uuid.UUID) -> list[ApiKey]:
        result = await self.session.execute(
            select(ApiKey)
            .where(ApiKey.workspace_id == workspace_id)
            .order_by(ApiKey.created_at.desc())
        )
        return list(result.scalars())

    async def add(self, key: ApiKey) -> ApiKey:
        self.session.add(key)
        await self.session.flush()
        return key
