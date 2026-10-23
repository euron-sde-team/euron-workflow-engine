"""Workspace variables, readable in templates as env.KEY."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, status

from workflow_engine.api.deps import EditorDep, SessionDep, ViewerDep
from workflow_engine.schemas.variables import VARIABLE_KEY, VariableIn, VariableOut
from workflow_engine.services.variables import VariableService

router = APIRouter(prefix="/api/v1/workspaces/{workspace}/variables", tags=["variables"])
Key = Annotated[str, Path(pattern=VARIABLE_KEY)]


@router.get("", summary="Every variable")
async def list_variables(ctx: ViewerDep, session: SessionDep) -> list[VariableOut]:
    return [VariableOut.model_validate(v) for v in await VariableService(session).all(ctx.id)]


@router.put("/{key}", summary="Create or replace a variable")
async def put_variable(
    key: Key, body: VariableIn, ctx: EditorDep, session: SessionDep
) -> VariableOut:
    variable = await VariableService(session).put(
        ctx.id, ctx.principal, key, body.value, body.description
    )
    return VariableOut.model_validate(variable)


@router.delete("/{key}", summary="Delete a variable", status_code=status.HTTP_204_NO_CONTENT)
async def delete_variable(key: Key, ctx: EditorDep, session: SessionDep) -> None:
    await VariableService(session).delete(ctx.id, ctx.principal, key)
