"""Credentials: create and manage encrypted secrets. Values are never returned."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from workflow_engine.api.deps import ContainerDep, EditorDep, SessionDep, ViewerDep
from workflow_engine.api.presenters import credential_out
from workflow_engine.schemas.credentials import CredentialCreate, CredentialOut, CredentialUpdate
from workflow_engine.services.vault import CredentialService

router = APIRouter(prefix="/api/v1/workspaces/{workspace}/credentials", tags=["credentials"])


@router.get("", summary="Credentials (metadata only)")
async def list_credentials(
    ctx: ViewerDep, container: ContainerDep, session: SessionDep
) -> list[CredentialOut]:
    rows = await CredentialService(container, session).all(ctx.id)
    return [credential_out(c, used_by) for c, used_by in rows]


@router.post("", summary="Store a credential (encrypted; never shown again)", status_code=201)
async def create_credential(
    body: CredentialCreate, ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> CredentialOut:
    credential = await CredentialService(container, session).create(
        ctx.id,
        ctx.principal,
        name=body.name,
        kind=body.type,
        description=body.description,
        data=body.data,
    )
    return credential_out(credential, [])


@router.get("/{credential_id}", summary="A credential's metadata")
async def get_credential(
    credential_id: uuid.UUID, ctx: ViewerDep, container: ContainerDep, session: SessionDep
) -> CredentialOut:
    service = CredentialService(container, session)
    credential = await service.get(ctx.id, credential_id)
    return credential_out(credential, await service.used_by(ctx.id, credential_id))


@router.patch("/{credential_id}", summary="Rename, or replace values (write-only)")
async def update_credential(
    credential_id: uuid.UUID,
    body: CredentialUpdate,
    ctx: EditorDep,
    container: ContainerDep,
    session: SessionDep,
) -> CredentialOut:
    service = CredentialService(container, session)
    credential = await service.update(
        ctx.id,
        ctx.principal,
        credential_id,
        name=body.name,
        description=body.description,
        data=body.data,
    )
    return credential_out(credential, await service.used_by(ctx.id, credential_id))


@router.delete(
    "/{credential_id}",
    summary="Delete a credential no workflow uses",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_credential(
    credential_id: uuid.UUID, ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> None:
    await CredentialService(container, session).delete(ctx.id, ctx.principal, credential_id)
