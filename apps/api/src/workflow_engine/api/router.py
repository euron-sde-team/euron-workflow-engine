from __future__ import annotations

from fastapi import APIRouter

from workflow_engine.api.routes import (
    api_keys,
    auth,
    catalog,
    credentials,
    health,
    variables,
    workflows,
    workspaces,
)

api_router = APIRouter()
for module in (health, auth, workspaces, catalog, workflows, credentials, variables, api_keys):
    api_router.include_router(module.router)
