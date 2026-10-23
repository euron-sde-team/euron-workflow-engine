"""`http.request`: call an HTTP API, with credentials from the vault and retries on failure.

Every request goes through the guarded client (integrations/http.py), so private and
metadata addresses are refused unless the operator allowed them. Responses are read up to
`max_response_kb`; larger bodies fail the step instead of filling the database.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
import orjson
from pydantic import Field

from workflow_engine.engine.definition import RetryPolicy
from workflow_engine.integrations.http import OutboundBlockedError
from workflow_engine.nodes.base import (
    NodeConfig,
    NodeContext,
    NodeError,
    NodeResult,
    NodeType,
    credential,
    templated,
)

HTTP_CREDENTIALS = frozenset({"http_bearer", "http_basic", "http_header", "http_query"})
_HIDDEN_RESPONSE_HEADERS = frozenset({"set-cookie", "authorization", "proxy-authenticate"})


class KeyValue(NodeConfig):
    name: str = Field(min_length=1, max_length=200)
    value: Any = ""


class HttpRequestConfig(NodeConfig):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"] = "GET"
    url: str = templated(..., min_length=1, max_length=4000)
    query: list[KeyValue] = templated(default_factory=list, widget="key-value", max_length=50)
    headers: list[KeyValue] = templated(default_factory=list, widget="key-value", max_length=50)
    body_type: Literal["none", "json", "text", "form"] = "none"
    body: Any = templated(None, widget="json")
    credential_id: uuid.UUID | None = credential(*sorted(HTTP_CREDENTIALS))
    timeout_s: float = Field(default=30, gt=0, le=300)
    response_format: Literal["auto", "json", "text"] = "auto"
    fail_on_http_error: bool = True
    retry_on_status: list[int] = Field(
        default_factory=lambda: [429, 500, 502, 503, 504], max_length=20
    )
    follow_redirects: bool = True
    max_response_kb: int = Field(default=1024, ge=1, le=10_240)


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return orjson.dumps(value).decode() if isinstance(value, dict | list) else str(value)


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if raw and raw.strip().isdigit():
        return min(float(raw.strip()), 3600.0)
    return None


async def _read_limited(response: httpx.Response, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > limit:
            raise NodeError(
                "response_too_large",
                f"The response is larger than {limit // 1024} KB. Raise max_response_kb or "
                "fetch less data.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _decode(body: bytes, content_type: str, fmt: str) -> Any:
    if fmt == "text" or not body:
        return body.decode("utf-8", errors="replace")
    if fmt == "json" or "json" in content_type:
        try:
            return orjson.loads(body)
        except orjson.JSONDecodeError as exc:
            if fmt == "json":
                raise NodeError("invalid_json", "The response is not valid JSON.") from exc
    return body.decode("utf-8", errors="replace")


async def run(ctx: NodeContext, config: HttpRequestConfig) -> NodeResult:
    parts = urlsplit(config.url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise NodeError("invalid_url", f"'{config.url}' is not an http or https URL.")
    headers = {h.name: _text(h.value) for h in config.headers}
    params = {q.name: _text(q.value) for q in config.query}
    auth: httpx.Auth | None = None
    if config.credential_id is not None:
        resolved = await ctx.credential(config.credential_id, HTTP_CREDENTIALS)
        values = resolved.values
        match resolved.type:
            case "http_bearer":
                headers["Authorization"] = f"Bearer {values['token']}"
            case "http_basic":
                auth = httpx.BasicAuth(str(values["username"]), str(values["password"]))
            case "http_header":
                headers[str(values["header_name"])] = str(values["header_value"])
            case "http_query":
                params[str(values["param_name"])] = str(values["param_value"])

    request_kwargs: dict[str, Any] = {}
    if config.method not in {"GET", "HEAD"} and config.body_type != "none":
        if config.body_type == "json":
            request_kwargs["content"] = orjson.dumps(config.body)
            headers.setdefault("Content-Type", "application/json")
        elif config.body_type == "text":
            request_kwargs["content"] = _text(config.body).encode()
            headers.setdefault("Content-Type", "text/plain; charset=utf-8")
        else:
            if not isinstance(config.body, dict):
                raise NodeError("invalid_body", "A form body must be an object of fields.")
            request_kwargs["data"] = {k: _text(v) for k, v in config.body.items()}

    started = time.perf_counter()
    try:
        async with ctx.services.http.stream(
            config.method,
            config.url,
            params=params or None,
            headers=headers,
            auth=auth,
            timeout=config.timeout_s,
            follow_redirects=config.follow_redirects,
            **request_kwargs,
        ) as response:
            body = await _read_limited(response, config.max_response_kb * 1024)
    except OutboundBlockedError as exc:
        raise NodeError("blocked_address", str(exc)) from exc
    except httpx.TimeoutException as exc:
        raise NodeError(
            "timeout",
            f"{config.method} {config.url} timed out after {config.timeout_s:g} s",
            retryable=True,
        ) from exc
    except httpx.TooManyRedirects as exc:
        raise NodeError("too_many_redirects", "The server redirected too many times.") from exc
    except httpx.TransportError as exc:
        raise NodeError(
            "network_error", f"{config.method} {config.url} failed: {exc}", retryable=True
        ) from exc
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    content_type = response.headers.get("content-type", "")
    payload = _decode(body, content_type, config.response_format)
    ctx.log(
        "info" if response.status_code < 400 else "warn",
        f"{config.method} {response.url} -> {response.status_code} in {elapsed_ms} ms",
        status=response.status_code,
        bytes=len(body),
    )
    if config.fail_on_http_error and response.status_code >= 400:
        retryable = response.status_code in config.retry_on_status
        excerpt = payload if isinstance(payload, dict | list) else _text(payload)[:500]
        raise NodeError(
            f"http_{response.status_code}",
            f"{config.method} {config.url} answered {response.status_code}",
            retryable=retryable,
            details={"status": response.status_code, "body": excerpt},
            retry_after_s=_retry_after(response),
        )
    return NodeResult(
        output={
            "status": response.status_code,
            "headers": {
                k.lower(): v
                for k, v in response.headers.items()
                if k.lower() not in _HIDDEN_RESPONSE_HEADERS
            },
            "body": payload,
            "url": str(response.url),
            "elapsed_ms": elapsed_ms,
        }
    )


NODES = [
    NodeType(
        type="http.request",
        name="HTTP request",
        category="integration",
        description="Call any HTTP API with a stored credential; retries on 429 and 5xx.",
        icon="globe",
        config_model=HttpRequestConfig,
        run=run,
        default_retry=RetryPolicy(max_attempts=3, initial_delay_ms=1000, max_delay_ms=30_000),
        default_timeout_s=60,
        side_effects=True,
        sample_output={"status": 200, "headers": {}, "body": {}, "url": "", "elapsed_ms": 42},
    )
]
