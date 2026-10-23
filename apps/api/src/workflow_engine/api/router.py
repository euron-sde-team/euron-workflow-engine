from __future__ import annotations

from fastapi import APIRouter

from workflow_engine.api.routes import api_keys, auth, health, workspaces

api_router = APIRouter()
for module in (health, auth, workspaces, api_keys):
    api_router.include_router(module.router)
