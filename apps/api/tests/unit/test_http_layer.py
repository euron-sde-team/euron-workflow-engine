"""The error envelope and the ASGI middleware, on a minimal app (no database)."""

import httpx
import pytest
from fastapi import FastAPI

from workflow_engine.core.context import BodySizeLimitMiddleware, RequestContextMiddleware
from workflow_engine.core.errors import NotFoundError, install_exception_handlers


def _app() -> FastAPI:
    app = FastAPI()
    install_exception_handlers(app)

    @app.get("/missing")
    async def missing() -> None:
        raise NotFoundError("Workflow not found.")

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internals")

    @app.get("/items/{item_id}")
    async def item(item_id: int) -> dict[str, int]:
        return {"id": item_id}

    @app.post("/echo")
    async def echo(payload: dict[str, str]) -> dict[str, str]:
        return payload

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=64)
    app.add_middleware(RequestContextMiddleware)
    return app


@pytest.fixture
async def client():  # type: ignore[no-untyped-def]
    transport = httpx.ASGITransport(app=_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_typed_errors_use_the_envelope_with_a_request_id(client: httpx.AsyncClient) -> None:
    response = await client.get("/missing", headers={"x-request-id": "req-123"})
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Workflow not found.", "request_id": "req-123"}
    }
    assert response.headers["x-request-id"] == "req-123"
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_unexpected_errors_hide_internals(client: httpx.AsyncClient) -> None:
    response = await client.get("/boom")
    assert response.status_code == 500
    assert "secret" not in response.text
    assert response.json()["error"]["code"] == "internal_error"


async def test_validation_errors_list_every_field(client: httpx.AsyncClient) -> None:
    response = await client.get("/items/not-a-number")
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["loc"] == ["path", "item_id"]


async def test_invalid_request_ids_are_replaced(client: httpx.AsyncClient) -> None:
    response = await client.get("/items/1", headers={"x-request-id": "bad id with spaces"})
    assert response.headers["x-request-id"] != "bad id with spaces"
    assert len(response.headers["x-request-id"]) == 32


async def test_oversized_bodies_are_refused_before_parsing(client: httpx.AsyncClient) -> None:
    response = await client.post("/echo", json={"text": "x" * 200})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
