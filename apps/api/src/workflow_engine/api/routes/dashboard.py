"""The workspace dashboard."""

from __future__ import annotations

from fastapi import APIRouter

from workflow_engine.api.deps import ContainerDep, SessionDep, ViewerDep
from workflow_engine.schemas.dashboard import DashboardOut, Window
from workflow_engine.services.dashboard import DashboardService
from workflow_engine.services.workspaces import workspace_settings

router = APIRouter(prefix="/api/v1/workspaces/{workspace}/dashboard", tags=["dashboard"])


@router.get("", summary="Success rate, volume, slowest workflows, failures, queue and workers")
async def dashboard(
    ctx: ViewerDep, container: ContainerDep, session: SessionDep, window: Window = "7d"
) -> DashboardOut:
    timezone = workspace_settings(ctx.workspace).timezone
    return await DashboardService(container, session).build(ctx.id, timezone, window)
