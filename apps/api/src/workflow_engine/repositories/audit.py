from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, tuple_

from workflow_engine.models import ApiKey, AuditEvent, User
from workflow_engine.repositories.base import Repository


class AuditRepository(Repository):
    async def add(self, event: AuditEvent) -> None:
        self.session.add(event)

    async def page(
        self,
        workspace_id: uuid.UUID,
        *,
        limit: int,
        after: tuple[datetime, uuid.UUID] | None = None,
        action: str | None = None,
        since: datetime | None = None,
    ) -> list[tuple[AuditEvent, str | None, str | None]]:
        query = (
            select(AuditEvent, User.name, ApiKey.name)
            .outerjoin(User, User.id == AuditEvent.actor_user_id)
            .outerjoin(ApiKey, ApiKey.id == AuditEvent.actor_api_key_id)
            .where(AuditEvent.workspace_id == workspace_id)
        )
        if after is not None:
            query = query.where(tuple_(AuditEvent.created_at, AuditEvent.id) < tuple_(*after))
        if action:
            query = query.where(AuditEvent.action.startswith(action))
        if since is not None:
            query = query.where(AuditEvent.created_at >= since)
        result = await self.session.execute(
            query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit)
        )
        return [(event, user, key) for event, user, key in result.all()]
