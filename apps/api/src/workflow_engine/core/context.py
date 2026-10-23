"""Per-request context: a request id on every log line and every response.

Implemented as a plain ASGI middleware rather than `BaseHTTPMiddleware`, so request bodies
and responses stream through without buffering (webhook signatures need the raw body).
"""

from __future__ import annotations

import re
import time
import uuid
from contextvars import ContextVar

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from workflow_engine.core import metrics
from workflow_engine.core.logging import get_logger

REQUEST_ID_HEADER = "x-request-id"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_QUIET_PATHS = frozenset({"/livez", "/readyz", "/metrics"})
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
log = get_logger("wfe.http")


def get_request_id() -> str | None:
    return _request_id.get()


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = _header(scope, REQUEST_ID_HEADER)
        request_id = (
            incoming if incoming and _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        )
        token = _request_id.set(request_id)
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        status = 500

        async def send_with_headers(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                headers.extend(_SECURITY_HEADERS)
                if self.hsts:
                    headers.append(
                        (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
                    )
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            elapsed = time.perf_counter() - started
            route = scope.get("route")
            template = getattr(route, "path", None) or "unmatched"
            method = scope.get("method", "GET")
            metrics.HTTP_REQUESTS.labels(method, template, str(status)).inc()
            metrics.HTTP_LATENCY.labels(method, template).observe(elapsed)
            if scope.get("path") not in _QUIET_PATHS:
                log.info(
                    "request",
                    method=method,
                    route=template,
                    status=status,
                    duration_ms=round(elapsed * 1000, 1),
                )
            structlog.contextvars.unbind_contextvars("request_id")
            _request_id.reset(token)


_SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (b"cross-origin-resource-policy", b"same-site"),
)


def _header(scope: Scope, name: str) -> str | None:
    target = name.encode()
    for key, value in scope.get("headers", []):
        if key == target:
            decoded: str = value.decode("latin-1")
            return decoded
    return None


class BodySizeLimitMiddleware:
    """Refuse request bodies over `max_bytes` before the multipart parser buffers them.

    Checks Content-Length up front and counts streamed (chunked) bodies as they arrive.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = _header(scope, "content-length")
        if declared and declared.isdigit() and int(declared) > self.max_bytes:
            await _reject_too_large(send)
            return
        received = 0

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLargeError
            return message

        try:
            await self.app(scope, counting_receive, send)
        except _BodyTooLargeError:
            await _reject_too_large(send)


class _BodyTooLargeError(Exception):
    pass


async def _reject_too_large(send: Send) -> None:
    body = (
        b'{"error":{"code":"payload_too_large","message":"The request body is larger than '
        b'this deployment allows.","request_id":null}}'
    )
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
