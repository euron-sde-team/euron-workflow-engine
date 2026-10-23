"""Public webhook ingress: /hooks/{workspace}/{path}."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from workflow_engine.api.deps import ContainerDep, SessionDep
from workflow_engine.services.webhooks import WebhookService

router = APIRouter(tags=["webhooks"])
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


async def receive_webhook(
    workspace: str, path: str, request: Request, container: ContainerDep, session: SessionDep
) -> JSONResponse:
    response = await WebhookService(container, session).receive(
        workspace_slug=workspace,
        path=path,
        method=request.method,
        headers={k.lower(): v for k, v in request.headers.items()},
        query=dict(request.query_params),
        body=await request.body(),
    )
    return JSONResponse(response.body, status_code=response.status_code)


# One route per method, so every operation in the OpenAPI document has its own id.
for _method in METHODS:
    router.add_api_route(
        "/hooks/{workspace}/{path:path}",
        receive_webhook,
        methods=[_method],
        operation_id=f"receive_webhook_{_method.lower()}",
        summary="Start the workflow listening on this path",
        responses={202: {"description": "Accepted"}, 200: {"description": "Duplicate or finished"}},
    )
