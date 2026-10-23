"""Dead letters: steps that exhausted their retries."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from workflow_engine.api.deps import ContainerDep, EditorDep, SessionDep, ViewerDep
from workflow_engine.api.presenters import dead_letter_out, execution_summary
from workflow_engine.schemas.common import CursorPage
from workflow_engine.schemas.executions import DeadLetterOut, ExecutionSummaryOut
from workflow_engine.services.executions import ExecutionService

router = APIRouter(prefix="/api/v1/workspaces/{workspace}/dead-letters", tags=["dead letters"])


@router.get("", summary="Dead letters, newest first")
async def list_dead_letters(
    ctx: ViewerDep,
    container: ContainerDep,
    session: SessionDep,
    status: Annotated[str | None, Query(pattern="^(open|retried|discarded)$")] = "open",
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> CursorPage[DeadLetterOut]:
    rows, next_cursor = await ExecutionService(container, session).dead_letters(
        ctx.id, status=status, limit=limit, cursor=cursor
    )
    return CursorPage(items=[dead_letter_out(d, name) for d, name in rows], next_cursor=next_cursor)


@router.post("/{letter_id}/retry", summary="Resume the execution from the failed step")
async def retry_dead_letter(
    letter_id: uuid.UUID, ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> ExecutionSummaryOut:
    service = ExecutionService(container, session)
    letter = await service.letter(ctx.id, letter_id)
    await service.resume(ctx.id, ctx.principal, letter.execution_id)
    detail = await service.detail(ctx.id, letter.execution_id)
    return execution_summary(detail.execution, detail.workflow_name)


@router.post("/{letter_id}/discard", summary="Close it without running anything")
async def discard_dead_letter(
    letter_id: uuid.UUID, ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> DeadLetterOut:
    service = ExecutionService(container, session)
    letter = await service.discard(ctx.id, ctx.principal, letter_id)
    rows, _ = await service.dead_letters(ctx.id, status=None, limit=1, cursor=None)
    name = next((n for d, n in rows if d.id == letter.id), "")
    return dead_letter_out(letter, name)
