"""Executions: history, detail, steps, logs, and cancel, resume or retry."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from workflow_engine.api.deps import ContainerDep, EditorDep, SessionDep, ViewerDep
from workflow_engine.api.presenters import execution_detail, execution_summary, step_detail
from workflow_engine.repositories.executions import ExecutionFilters
from workflow_engine.schemas.common import CursorPage
from workflow_engine.schemas.executions import (
    ExecutionOut,
    ExecutionSummaryOut,
    LogOut,
    LogPage,
    StepOut,
)
from workflow_engine.schemas.workflows import RunOut
from workflow_engine.services.executions import ExecutionService

router = APIRouter(prefix="/api/v1/workspaces/{workspace}/executions", tags=["executions"])
Status = Annotated[
    str | None, Query(pattern="^(queued|running|waiting|succeeded|failed|cancelled)$")
]


@router.get("", summary="Executions, newest first, with filters and a cursor")
async def list_executions(
    ctx: ViewerDep,
    container: ContainerDep,
    session: SessionDep,
    workflow_id: uuid.UUID | None = None,
    status: Status = None,
    trigger: Annotated[
        str | None, Query(pattern="^(manual|webhook|cron|interval|event|retry)$")
    ] = None,
    mode: Annotated[str | None, Query(pattern="^(production|manual|test)$")] = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> CursorPage[ExecutionSummaryOut]:
    rows, next_cursor = await ExecutionService(container, session).page(
        ctx.id,
        ExecutionFilters(workflow_id, status, trigger, mode, since, until),
        limit=limit,
        cursor=cursor,
    )
    return CursorPage(
        items=[execution_summary(e, name) for e, name in rows], next_cursor=next_cursor
    )


@router.get("/{execution_id}", summary="An execution with its step timeline")
async def get_execution(
    execution_id: uuid.UUID, ctx: ViewerDep, container: ContainerDep, session: SessionDep
) -> ExecutionOut:
    return execution_detail(await ExecutionService(container, session).detail(ctx.id, execution_id))


@router.get("/{execution_id}/steps/{step_id}", summary="One step with its input and output")
async def get_step(
    execution_id: uuid.UUID,
    step_id: uuid.UUID,
    ctx: ViewerDep,
    container: ContainerDep,
    session: SessionDep,
) -> StepOut:
    step = await ExecutionService(container, session).step(ctx.id, execution_id, step_id)
    return step_detail(step)


@router.get("/{execution_id}/logs", summary="Log lines, oldest first")
async def get_logs(
    execution_id: uuid.UUID,
    ctx: ViewerDep,
    container: ContainerDep,
    session: SessionDep,
    step_id: uuid.UUID | None = None,
    after: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> LogPage:
    rows = await ExecutionService(container, session).logs(
        ctx.id, execution_id, step_id=step_id, after_id=after, limit=limit + 1
    )
    items = [LogOut.model_validate(r) for r in rows[:limit]]
    return LogPage(items=items, next_after=items[-1].id if len(rows) > limit else None)


@router.post("/{execution_id}/cancel", summary="Cancel a queued, running or waiting execution")
async def cancel_execution(
    execution_id: uuid.UUID, ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> ExecutionSummaryOut:
    service = ExecutionService(container, session)
    await service.cancel(ctx.id, ctx.principal, execution_id)
    detail = await service.detail(ctx.id, execution_id)
    return execution_summary(detail.execution, detail.workflow_name)


@router.post("/{execution_id}/resume", summary="Resume a failed execution from its failed step")
async def resume_execution(
    execution_id: uuid.UUID, ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> ExecutionSummaryOut:
    service = ExecutionService(container, session)
    await service.resume(ctx.id, ctx.principal, execution_id)
    detail = await service.detail(ctx.id, execution_id)
    return execution_summary(detail.execution, detail.workflow_name)


@router.post(
    "/{execution_id}/retry",
    summary="Run again from the start with the same payload",
    status_code=201,
)
async def retry_execution(
    execution_id: uuid.UUID, ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> RunOut:
    result = await ExecutionService(container, session).retry(ctx.id, ctx.principal, execution_id)
    return RunOut(execution_id=result.execution.id, status=result.execution.status)
