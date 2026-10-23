from __future__ import annotations

from fastapi import APIRouter

from workflow_engine.api.routes import (
    api_keys,
    auth,
    catalog,
    credentials,
    dead_letters,
    events,
    executions,
    health,
    hooks,
    nodes,
    variables,
    workflows,
    workspaces,
)

api_router = APIRouter()
for module in (
    health,
    auth,
    workspaces,
    catalog,
    workflows,
    nodes,
    executions,
    dead_letters,
    events,
    credentials,
    variables,
    api_keys,
    hooks,
):
    api_router.include_router(module.router)
