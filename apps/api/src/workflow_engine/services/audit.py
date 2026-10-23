"""The audit trail: recorded inside the transaction of the change it describes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from workflow_engine.core import cursor as cursors
from workflow_engine.models import AuditEvent
from workflow_engine.repositories.audit import AuditRepository
from workflow_engine.schemas.audit import AuditEventOut
from workflow_engine.schemas.common import CursorPage
from workflow_engine.services.principal import Principal


async def record(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID | None,
    principal: Principal | None,
    action: str,
    target_type: str,
    target_id: object | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Add an audit event to the caller's transaction (it commits with the change it records)."""
    await AuditRepository(session).add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=principal.user_id if principal else None,
            actor_api_key_id=principal.api_key_id if principal else None,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            details=details or {},
        )
    )


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.audit = AuditRepository(session)

    async def page(
        self,
        workspace_id: uuid.UUID,
        *,
        limit: int,
        cursor: str | None,
        action: str | None = None,
        since: datetime | None = None,
    ) -> CursorPage[AuditEventOut]:
        after = cursors.decode_uuid(cursor) if cursor else None
        rows = await self.audit.page(
            workspace_id, limit=limit + 1, after=after, action=action, since=since
        )
        items = [
            AuditEventOut(
                id=event.id,
                action=event.action,
                target_type=event.target_type,
                target_id=event.target_id,
                details=event.details,
                actor_type=(
                    "user"
                    if event.actor_user_id
                    else "api_key"
                    if event.actor_api_key_id
                    else "system"
                ),
                actor_name=user_name or key_name,
                created_at=event.created_at,
            )
            for event, user_name, key_name in rows[:limit]
        ]
        next_cursor = (
            cursors.encode(items[-1].created_at, items[-1].id) if len(rows) > limit else None
        )
        return CursorPage(items=items, next_cursor=next_cursor)
