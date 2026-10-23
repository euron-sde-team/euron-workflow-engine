"""The FastAPI application factory.

uvicorn workflow_engine.main:create_app --factory --port 8130
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from workflow_engine import __version__
from workflow_engine.api.router import api_router
from workflow_engine.core.config import Settings, get_settings
from workflow_engine.core.context import BodySizeLimitMiddleware, RequestContextMiddleware
from workflow_engine.core.errors import install_exception_handlers
from workflow_engine.core.logging import configure_logging, get_logger
from workflow_engine.db.migrate import migrate
from workflow_engine.services.container import build_container

log = get_logger("wfe.app")

DESCRIPTION = """
Self-hosted workflow automation: workflows, versions, triggers, durable executions with
retries, a credentials vault, an event bus and run history.

Authenticate with the session cookie set by `POST /api/v1/auth/login`, or with
`Authorization: Bearer <token>` using either a session token or a workspace API key
(`wfk_...`). Webhook triggers are served outside `/api` at `/hooks/{workspace}/{path}`.
Every error uses one envelope: `{"error": {"code", "message", "request_id", "details?"}}`.
"""

TAGS = [
    {"name": "auth", "description": "Sign-in, sign-up, sessions and your profile."},
    {"name": "workspaces", "description": "Workspaces, members, roles and the audit trail."},
    {"name": "catalog", "description": "Node types, credential types and the template gallery."},
    {"name": "workflows", "description": "Drafts, validation, versions, activation, runs."},
    {"name": "executions", "description": "Run history, steps, logs, cancel, resume, retry."},
    {"name": "dead letters", "description": "Steps that exhausted their retries."},
    {"name": "credentials", "description": "Encrypted secrets; values are never returned."},
    {"name": "events", "description": "The workspace event bus."},
    {"name": "variables", "description": "Non-secret workspace settings for templates."},
    {"name": "dashboard", "description": "Success rate, volume, slow workflows, queue."},
    {"name": "api keys", "description": "Workspace-scoped keys for programmatic access."},
    {"name": "webhooks", "description": "Public ingress for webhook triggers and resumes."},
    {"name": "system", "description": "Deployment capabilities and limits."},
]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)
    if settings.is_production and (problems := settings.production_problems()):
        raise RuntimeError("Refusing to start in production:\n  - " + "\n  - ".join(problems))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.migrate_on_boot:
            await migrate(settings)
        container = build_container(settings)
        app.state.container = container
        log.info(
            "started",
            version=__version__,
            env=settings.app_env,
            vault=container.keys.name,
            node_types=len(container.registry),
        )
        try:
            yield
        finally:
            await container.close()

    app = FastAPI(
        title=settings.product_name,
        version=__version__,
        description=DESCRIPTION,
        openapi_tags=TAGS,
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
        license_info={"name": "MIT", "identifier": "MIT"},
    )
    install_exception_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["authorization", "content-type", "x-request-id", "idempotency-key"],
        expose_headers=[
            "x-request-id",
            "x-ratelimit-limit",
            "x-ratelimit-remaining",
            "x-ratelimit-reset",
            "content-disposition",
        ],
        max_age=600,
    )
    # Workflow definitions (256 KB), webhook bodies and test payloads stay well under this.
    app.add_middleware(
        BodySizeLimitMiddleware,
        max_bytes=max(settings.webhook_max_body_bytes, settings.max_payload_bytes) + 64 * 1024,
    )
    app.add_middleware(RequestContextMiddleware, hsts=settings.is_production)
    app.include_router(api_router)
    return app
