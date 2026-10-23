"""Workspace API keys (owner only). The reference resource: see apps/api/README.md."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from workflow_engine.api.deps import ContainerDep, OwnerDep, SessionDep
from workflow_engine.schemas.api_keys import ApiKeyCreate, ApiKeyCreated, ApiKeyOut
from workflow_engine.services.api_keys import ApiKeyService

router = APIRouter(prefix="/api/v1/workspaces/{workspace}/api-keys", tags=["api keys"])


@router.get("", summary="Keys for this workspace")
async def list_keys(ctx: OwnerDep, container: ContainerDep, session: SessionDep) -> list[ApiKeyOut]:
    return [
        ApiKeyOut.model_validate(k)
        for k in await ApiKeyService(container, session).for_workspace(ctx.id)
    ]


@router.post(
    "", summary="Create a key (the secret is shown once)", status_code=status.HTTP_201_CREATED
)
async def create_key(
    body: ApiKeyCreate, ctx: OwnerDep, container: ContainerDep, session: SessionDep
) -> ApiKeyCreated:
    key, plaintext = await ApiKeyService(container, session).create(
        ctx.workspace, ctx.principal, body.name, body.role, body.expires_in_days
    )
    return ApiKeyCreated.model_validate(
        {**ApiKeyOut.model_validate(key).model_dump(), "key": plaintext}
    )


@router.delete("/{key_id}", summary="Revoke a key", status_code=204)
async def revoke_key(
    key_id: uuid.UUID, ctx: OwnerDep, container: ContainerDep, session: SessionDep
) -> None:
    await ApiKeyService(container, session).revoke(ctx.workspace, ctx.principal, key_id)
