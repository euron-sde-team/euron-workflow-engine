"""The workspace event bus."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from workflow_engine.api.deps import ContainerDep, EditorDep, SessionDep, ViewerDep, rate_limit
from workflow_engine.api.presenters import event_out
from workflow_engine.schemas.common import CursorPage
from workflow_engine.schemas.events import EventOut, EventPublish, EventPublished
from workflow_engine.services.events import EventService

router = APIRouter(prefix="/api/v1/workspaces/{workspace}/events", tags=["events"])


@router.post(
    "",
    summary="Publish an event; every active workflow listening for it starts",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("events", "rate_limit_events"))],
)
async def publish_event(
    body: EventPublish, ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> EventPublished:
    event, started = await EventService(container, session).publish(
        ctx.id, ctx.principal, body.name, body.payload
    )
    return EventPublished(event_id=event.id, matched=len(started), executions=started)


@router.get("", summary="Events, newest first")
async def list_events(
    ctx: ViewerDep,
    container: ContainerDep,
    session: SessionDep,
    name: Annotated[str | None, Query(max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> CursorPage[EventOut]:
    rows, next_cursor = await EventService(container, session).page(
        ctx.id, name=name, limit=limit, cursor=cursor
    )
    return CursorPage(items=[event_out(e) for e in rows], next_cursor=next_cursor)
