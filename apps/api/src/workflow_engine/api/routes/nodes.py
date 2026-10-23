"""Test-run a single node with sample data."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from workflow_engine.api.deps import ContainerDep, EditorDep, SessionDep, rate_limit
from workflow_engine.schemas.nodes import NodeTestRequest, NodeTestResult
from workflow_engine.services.node_tests import NodeTestService

router = APIRouter(prefix="/api/v1/workspaces/{workspace}/nodes", tags=["workflows"])


@router.post(
    "/test",
    summary="Run one node now and return its output (nothing is stored)",
    dependencies=[Depends(rate_limit("node-test", "rate_limit_test_run"))],
)
async def test_node(
    body: NodeTestRequest, ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> NodeTestResult:
    return await NodeTestService(container, session).run(ctx.id, body)
