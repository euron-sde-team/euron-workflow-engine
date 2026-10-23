"""Workflows: list, create, drafts, validation, publishing, activation, versions, export."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse

from workflow_engine.api.deps import ContainerDep, EditorDep, SessionDep, ViewerDep
from workflow_engine.api.presenters import issue_out, workflow_detail, workflow_summary
from workflow_engine.schemas.common import Page
from workflow_engine.schemas.workflows import (
    DraftSave,
    DraftSaved,
    ImportResult,
    IssueOut,
    PublishRequest,
    ValidateRequest,
    VersionDetailOut,
    VersionOut,
    WorkflowCreate,
    WorkflowOut,
    WorkflowSummaryOut,
    WorkflowUpdate,
)
from workflow_engine.services.container import Container
from workflow_engine.services.workflows import WorkflowService, parse_definition

router = APIRouter(prefix="/api/v1/workspaces/{workspace}/workflows", tags=["workflows"])


async def _detail(
    service: WorkflowService, container: Container, ctx: Any, workflow_id: uuid.UUID
) -> WorkflowOut:
    view = await service.view(ctx.id, workflow_id)
    return workflow_detail(view, ctx.workspace, container.settings.hooks_base_url)


@router.get("", summary="Workflows in this workspace, active first")
async def list_workflows(
    ctx: ViewerDep,
    container: ContainerDep,
    session: SessionDep,
    search: Annotated[str | None, Query(max_length=120)] = None,
    tag: Annotated[str | None, Query(max_length=32)] = None,
    active: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[WorkflowSummaryOut]:
    views, total = await WorkflowService(container, session).page(
        ctx.id, search=search, tag=tag, active=active, limit=limit, offset=offset
    )
    return Page(items=[workflow_summary(v) for v in views], total=total, limit=limit, offset=offset)


@router.post(
    "", summary="Create a workflow: blank, from a template or from a definition", status_code=201
)
async def create_workflow(
    body: WorkflowCreate, ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> WorkflowOut:
    service = WorkflowService(container, session)
    if body.template:
        workflow, _ = await service.create_from_template(
            ctx.workspace, ctx.principal, body.template, body.name
        )
    else:
        workflow = await service.create(
            ctx.workspace,
            ctx.principal,
            name=body.name,
            description=body.description,
            tags=body.tags,
            definition=body.definition,
        )
    return await _detail(service, container, ctx, workflow.id)


@router.post("/import", summary="Import an exported workflow document", status_code=201)
async def import_workflow(
    body: dict[str, Any], ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> ImportResult:
    service = WorkflowService(container, session)
    workflow, missing = await service.import_document(ctx.workspace, ctx.principal, body)
    return ImportResult(
        workflow=await _detail(service, container, ctx, workflow.id),
        unresolved_credentials=missing,
    )


@router.get("/{workflow_id}", summary="A workflow with its draft, triggers and issues")
async def get_workflow(
    workflow_id: uuid.UUID, ctx: ViewerDep, container: ContainerDep, session: SessionDep
) -> WorkflowOut:
    return await _detail(WorkflowService(container, session), container, ctx, workflow_id)


@router.patch("/{workflow_id}", summary="Rename, tag, or change the concurrency limit and timeout")
async def update_workflow(
    workflow_id: uuid.UUID,
    body: WorkflowUpdate,
    ctx: EditorDep,
    container: ContainerDep,
    session: SessionDep,
) -> WorkflowOut:
    service = WorkflowService(container, session)
    await service.update(
        ctx.id,
        ctx.principal,
        workflow_id,
        name=body.name,
        description=body.description,
        tags=body.tags,
        concurrency_limit=body.concurrency_limit,
        clear_concurrency_limit=body.clear_concurrency_limit,
        timeout_s=body.timeout_s,
    )
    return await _detail(service, container, ctx, workflow_id)


@router.put(
    "/{workflow_id}/draft", summary="Save the draft (optimistic: send the revision you edited)"
)
async def save_draft(
    workflow_id: uuid.UUID,
    body: DraftSave,
    ctx: EditorDep,
    container: ContainerDep,
    session: SessionDep,
) -> DraftSaved:
    workflow, issues = await WorkflowService(container, session).save_draft(
        ctx.id, ctx.principal, workflow_id, body.definition, body.revision
    )
    return DraftSaved(
        revision=workflow.draft_revision,
        updated_at=workflow.draft_updated_at,
        issues=[issue_out(i) for i in issues],
    )


@router.post("/{workflow_id}/validate", summary="Validate the draft, or a definition you send")
async def validate_workflow(
    workflow_id: uuid.UUID,
    body: ValidateRequest,
    ctx: ViewerDep,
    container: ContainerDep,
    session: SessionDep,
) -> list[IssueOut]:
    service = WorkflowService(container, session)
    workflow = await service.get(ctx.id, workflow_id)
    raw = body.definition if body.definition is not None else workflow.draft
    if body.definition is not None:
        parse_definition(raw)
    return [issue_out(i) for i in await service.issues(ctx.id, raw)]


@router.post("/{workflow_id}/publish", summary="Publish the draft as a new immutable version")
async def publish_workflow(
    workflow_id: uuid.UUID,
    body: PublishRequest,
    ctx: EditorDep,
    container: ContainerDep,
    session: SessionDep,
) -> WorkflowOut:
    service = WorkflowService(container, session)
    await service.publish(
        ctx.workspace, ctx.principal, workflow_id, note=body.note, activate=body.activate
    )
    return await _detail(service, container, ctx, workflow_id)


@router.post("/{workflow_id}/activate", summary="Start listening to triggers (published version)")
async def activate_workflow(
    workflow_id: uuid.UUID, ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> WorkflowOut:
    service = WorkflowService(container, session)
    await service.activate(ctx.workspace, ctx.principal, workflow_id)
    return await _detail(service, container, ctx, workflow_id)


@router.post("/{workflow_id}/deactivate", summary="Stop listening to triggers")
async def deactivate_workflow(
    workflow_id: uuid.UUID, ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> WorkflowOut:
    service = WorkflowService(container, session)
    await service.deactivate(ctx.id, ctx.principal, workflow_id)
    return await _detail(service, container, ctx, workflow_id)


@router.get("/{workflow_id}/versions", summary="Published versions, newest first")
async def list_versions(
    workflow_id: uuid.UUID, ctx: ViewerDep, container: ContainerDep, session: SessionDep
) -> list[VersionOut]:
    service = WorkflowService(container, session)
    workflow = await service.get(ctx.id, workflow_id)
    return [
        VersionOut(
            id=v.id,
            number=v.number or 0,
            note=v.note,
            checksum=v.checksum,
            node_count=len(v.definition.get("nodes", [])),
            created_at=v.created_at,
            is_current=v.id == workflow.published_version_id,
        )
        for v in await service.versions_of(ctx.id, workflow_id)
    ]


@router.get("/{workflow_id}/versions/{number}", summary="One published version")
async def get_version(
    workflow_id: uuid.UUID,
    number: int,
    ctx: ViewerDep,
    container: ContainerDep,
    session: SessionDep,
) -> VersionDetailOut:
    service = WorkflowService(container, session)
    workflow = await service.get(ctx.id, workflow_id)
    v = await service.version(ctx.id, workflow_id, number)
    return VersionDetailOut(
        id=v.id,
        number=v.number or 0,
        note=v.note,
        checksum=v.checksum,
        node_count=len(v.definition.get("nodes", [])),
        created_at=v.created_at,
        is_current=v.id == workflow.published_version_id,
        definition=v.definition,
    )


@router.post("/{workflow_id}/versions/{number}/restore", summary="Copy a version into the draft")
async def restore_version(
    workflow_id: uuid.UUID,
    number: int,
    ctx: EditorDep,
    container: ContainerDep,
    session: SessionDep,
) -> WorkflowOut:
    service = WorkflowService(container, session)
    await service.restore(ctx.id, ctx.principal, workflow_id, number)
    return await _detail(service, container, ctx, workflow_id)


@router.post("/{workflow_id}/duplicate", summary="Copy the workflow (draft only)", status_code=201)
async def duplicate_workflow(
    workflow_id: uuid.UUID, ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> WorkflowOut:
    service = WorkflowService(container, session)
    copy = await service.duplicate(ctx.workspace, ctx.principal, workflow_id)
    return await _detail(service, container, ctx, copy.id)


@router.get("/{workflow_id}/export", summary="Export as a portable JSON document")
async def export_workflow(
    workflow_id: uuid.UUID,
    ctx: ViewerDep,
    container: ContainerDep,
    session: SessionDep,
    published: bool = False,
) -> JSONResponse:
    document = await WorkflowService(container, session).export(
        ctx.id, workflow_id, published=published
    )
    filename = "".join(c if c.isalnum() else "-" for c in document["name"].lower()).strip("-")
    return JSONResponse(
        document,
        headers={"content-disposition": f'attachment; filename="{filename or "workflow"}.json"'},
    )


@router.delete(
    "/{workflow_id}",
    summary="Delete a workflow and its history",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_workflow(
    workflow_id: uuid.UUID, ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> None:
    await WorkflowService(container, session).delete(ctx.id, ctx.principal, workflow_id)
