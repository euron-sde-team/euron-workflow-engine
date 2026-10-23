"""The event bus from the API's side: publish and browse events."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from workflow_engine.core import cursor as cursors
from workflow_engine.models import Event
from workflow_engine.models.enums import EventSource
from workflow_engine.services import audit
from workflow_engine.services.container import Container
from workflow_engine.services.engine import Engine
from workflow_engine.services.principal import Principal


class EventService:
    def __init__(self, container: Container, session: AsyncSession) -> None:
        self.c = container
        self.session = session

    async def publish(
        self, workspace_id: uuid.UUID, principal: Principal, name: str, payload: Any
    ) -> tuple[Event, list[uuid.UUID]]:
        engine = Engine(self.c, self.session)
        event, started = await engine.publish_event(
            workspace_id=workspace_id,
            name=name,
            payload=engine.sized(payload, "event payload"),
            source=EventSource.API,
            admit_now=True,
        )
        await audit.record(
            self.session,
            workspace_id=workspace_id,
            principal=principal,
            action="event.published",
            target_type="event",
            target_id=event.id,
            details={"name": name, "matched": len(started)},
        )
        await engine.commit()
        return event, [execution.id for execution in started]

    async def page(
        self, workspace_id: uuid.UUID, *, name: str | None, limit: int, cursor: str | None
    ) -> tuple[list[Event], str | None]:
        query = select(Event).where(Event.workspace_id == workspace_id)
        if name:
            query = query.where(Event.name.startswith(name.rstrip("*")))
        if cursor:
            moment, row_id = cursors.decode_uuid(cursor)
            query = query.where(tuple_(Event.created_at, Event.id) < tuple_(moment, row_id))
        rows = list(
            (
                await self.session.execute(
                    query.order_by(Event.created_at.desc(), Event.id.desc()).limit(limit + 1)
                )
            ).scalars()
        )
        next_cursor = (
            cursors.encode(rows[limit - 1].created_at, rows[limit - 1].id)
            if len(rows) > limit
            else None
        )
        return rows[:limit], next_cursor

    async def recent_names(self, workspace_id: uuid.UUID, since: datetime) -> list[str]:
        result = await self.session.execute(
            select(Event.name)
            .where(Event.workspace_id == workspace_id, Event.created_at >= since)
            .group_by(Event.name)
            .order_by(Event.name)
        )
        return list(result.scalars())
