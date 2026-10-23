"""Webhook ingress: route, authenticate, deduplicate and start an execution.

Signing secrets are decrypted through the vault on first use and kept in process memory
for at most a minute, keyed by credential version, so a busy webhook does not call KMS on
every request and a rotated secret takes effect at once.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl

import orjson
from sqlalchemy.ext.asyncio import AsyncSession

from workflow_engine.core import metrics
from workflow_engine.core.crypto import constant_time_equals, verify_signature
from workflow_engine.core.errors import (
    AppError,
    MethodNotAllowedError,
    NotFoundError,
    PayloadTooLargeError,
    RateLimitedError,
    ServiceUnavailableError,
    UnauthorizedError,
    UnprocessableError,
)
from workflow_engine.integrations.keys import KeyProviderError
from workflow_engine.models import Execution, Workflow
from workflow_engine.models.enums import ExecutionMode, ExecutionStatus, TriggerKind
from workflow_engine.nodes.triggers import WebhookTriggerConfig
from workflow_engine.repositories.credentials import CredentialRepository
from workflow_engine.repositories.workflows import TriggerRepository
from workflow_engine.repositories.workspaces import WorkspaceRepository
from workflow_engine.services.container import Container
from workflow_engine.services.engine import Engine
from workflow_engine.services.vault import decrypt

_HIDDEN_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization"})
_SECRET_TTL_S = 60.0
_secrets: dict[tuple[uuid.UUID, int], tuple[float, str]] = {}


@dataclass(frozen=True, slots=True)
class WebhookResponse:
    status_code: int
    body: dict[str, Any]


def _parse_body(raw: bytes, content_type: str) -> Any:
    if not raw:
        return None
    if "json" in content_type:
        try:
            return orjson.loads(raw)
        except orjson.JSONDecodeError as exc:
            raise UnprocessableError("The body is not valid JSON.", code="invalid_json") from exc
    if "application/x-www-form-urlencoded" in content_type:
        return dict(parse_qsl(raw.decode("utf-8", errors="replace"), keep_blank_values=True))
    return raw.decode("utf-8", errors="replace")


class WebhookService:
    def __init__(self, container: Container, session: AsyncSession) -> None:
        self.c = container
        self.session = session

    async def _secret(self, workspace_id: uuid.UUID, credential_id: uuid.UUID) -> str:
        credential = await CredentialRepository(self.session).get(workspace_id, credential_id)
        if credential is None or credential.type != "webhook_secret":
            raise ServiceUnavailableError("The webhook's signing secret is missing.")
        key = (credential.id, credential.version)
        cached = _secrets.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        try:
            values = await decrypt(self.c, credential)
        except KeyProviderError as exc:
            raise ServiceUnavailableError("The signing secret could not be decrypted.") from exc
        secret = str(values["secret"])
        _secrets[key] = (time.monotonic() + _SECRET_TTL_S, secret)
        return secret

    async def _authenticate(
        self,
        workspace_id: uuid.UUID,
        config: WebhookTriggerConfig,
        headers: dict[str, str],
        body: bytes,
    ) -> None:
        if config.auth == "none" or config.credential_id is None:
            return
        secret = await self._secret(workspace_id, config.credential_id)
        if config.auth == "bearer":
            provided = headers.get(config.token_header.lower(), "")
            token = provided[7:] if provided.lower().startswith("bearer ") else provided
            if not token or not constant_time_equals(token.strip(), secret):
                raise UnauthorizedError(
                    "The webhook token is missing or wrong.", code="invalid_token"
                )
            return
        signature = headers.get(config.signature_header.lower())
        if not signature:
            raise UnauthorizedError(
                f"The {config.signature_header} header is missing.", code="missing_signature"
            )
        timestamp: str | None = None
        if config.timestamp_header:
            timestamp = headers.get(config.timestamp_header.lower())
            if not timestamp or not timestamp.strip().isdigit():
                raise UnauthorizedError(
                    f"The {config.timestamp_header} header is missing.", code="missing_timestamp"
                )
            age = abs(time.time() - int(timestamp.strip()))
            if age > config.tolerance_s:
                raise UnauthorizedError(
                    "The request is too old (or its clock is wrong).", code="stale_request"
                )
            timestamp = timestamp.strip()
        if not verify_signature(
            secret, body, signature, prefix=config.signature_prefix, timestamp=timestamp
        ):
            raise UnauthorizedError("The signature does not match.", code="invalid_signature")

    async def receive(
        self,
        *,
        workspace_slug: str,
        path: str,
        method: str,
        headers: dict[str, str],
        query: dict[str, str],
        body: bytes,
    ) -> WebhookResponse:
        try:
            return await self._receive(workspace_slug, path, method, headers, query, body)
        except AppError as exc:
            metrics.WEBHOOKS.labels(exc.code).inc()
            raise

    async def _receive(
        self,
        workspace_slug: str,
        path: str,
        method: str,
        headers: dict[str, str],
        query: dict[str, str],
        body: bytes,
    ) -> WebhookResponse:
        workspace = await WorkspaceRepository(self.session).by_slug(workspace_slug.lower())
        trigger = (
            await TriggerRepository(self.session).webhook_owner(workspace.id, path.strip("/"))
            if workspace
            else None
        )
        if workspace is None or trigger is None:
            raise NotFoundError(
                "No active workflow listens on this webhook.", code="webhook_not_found"
            )
        config = WebhookTriggerConfig.model_validate(trigger.config)
        if method.upper() != config.method:
            raise MethodNotAllowedError(f"This webhook accepts {config.method} requests.")
        if len(body) > self.c.settings.webhook_max_body_bytes:
            raise PayloadTooLargeError("The webhook body is larger than this deployment allows.")
        limit = await self.c.limiter.hit(f"hook:{trigger.id}", self.c.settings.rate_limit_webhook)
        if not limit.allowed:
            raise RateLimitedError(headers={"retry-after": str(limit.reset_s), **limit.headers()})
        await self._authenticate(workspace.id, config, headers, body)
        payload = {
            "method": method.upper(),
            "path": path.strip("/"),
            "headers": {
                k: v
                for k, v in headers.items()
                if k not in _HIDDEN_HEADERS and k != config.signature_header.lower()
            },
            "query": query,
            "body": _parse_body(body, headers.get("content-type", "")),
            "received_at": datetime.now(UTC).isoformat(),
        }
        key = headers.get(config.idempotency_header.lower(), "").strip()[:200] or None
        workflow = await self.session.get(Workflow, trigger.workflow_id)
        if workflow is None or not workflow.active:
            raise NotFoundError(
                "No active workflow listens on this webhook.", code="webhook_not_found"
            )
        engine = Engine(self.c, self.session)
        result = await engine.start(
            workflow=workflow,
            version_id=trigger.version_id,
            trigger_node_id=trigger.node_id,
            payload=payload,
            mode=ExecutionMode.PRODUCTION,
            trigger_kind=TriggerKind.WEBHOOK,
            idempotency_key=f"hook:{key}" if key else None,
        )
        execution_id = result.execution.id
        await engine.commit()
        metrics.WEBHOOKS.labels("duplicate" if result.duplicate else "accepted").inc()
        body_out: dict[str, Any] = {
            "execution_id": str(execution_id),
            "status": result.execution.status,
            "duplicate": result.duplicate,
        }
        if config.response == "when_finished":
            finished = await self._wait(execution_id, config.response_timeout_s)
            if finished is not None:
                body_out.update(
                    status=finished.status, output=finished.output, error=finished.error
                )
                return WebhookResponse(200, body_out)
        return WebhookResponse(200 if result.duplicate else 202, body_out)

    async def _wait(self, execution_id: uuid.UUID, timeout_s: int) -> Execution | None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            await asyncio.sleep(0.25)
            async with self.c.db.session() as session:
                execution = await session.get(Execution, execution_id)
                if execution is not None and ExecutionStatus(execution.status).is_terminal:
                    return execution
        return None
