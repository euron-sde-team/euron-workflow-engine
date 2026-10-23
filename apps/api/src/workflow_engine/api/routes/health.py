"""Probes, metrics and public deployment info."""

from __future__ import annotations

from typing import Any

import orjson
from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis.exceptions import RedisError

from workflow_engine import __version__
from workflow_engine.api.deps import ContainerDep, SessionDep
from workflow_engine.core import metrics
from workflow_engine.core.logging import get_logger
from workflow_engine.repositories.users import UserRepository
from workflow_engine.schemas.system import SystemInfo

router = APIRouter()
log = get_logger("wfe.health")
QUEUE_STATS_KEY = "wfe:stats:queue"


@router.get("/livez", include_in_schema=False)
async def livez() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
async def readyz(container: ContainerDep) -> JSONResponse:
    checks: dict[str, Any] = {}
    for name, probe in (
        ("database", container.db.ping),
        ("redis", container.redis.ping),
        ("vault", container.keys.check),
    ):
        try:
            await probe()
            checks[name] = "ok"
        except Exception as exc:
            log.warning("readiness_check_failed", check=name, error=type(exc).__name__)
            checks[name] = "failing"
    ready = all(value == "ok" for value in checks.values())
    return JSONResponse(
        {"status": "ready" if ready else "degraded", "checks": checks},
        status_code=200 if ready else 503,
    )


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics(container: ContainerDep) -> Response:
    # Queue depth is computed by the scheduler leader; every process reports the same value.
    try:
        raw = await container.redis.get(QUEUE_STATS_KEY)
        if raw:
            for kind, states in orjson.loads(raw).items():
                for state, count in states.items():
                    metrics.QUEUE_DEPTH.labels(kind, state).set(count)
    except (RedisError, orjson.JSONDecodeError, AttributeError):
        log.warning("queue_stats_unavailable")
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/api/v1/system/info", tags=["system"], summary="Deployment capabilities and limits")
async def system_info(container: ContainerDep, session: SessionDep) -> SystemInfo:
    settings = container.settings
    return SystemInfo(
        product_name=settings.product_name,
        version=__version__,
        hooks_base_url=settings.hooks_base_url,
        allow_signup=settings.allow_signup,
        needs_setup=await UserRepository(session).count() == 0,
        vault_provider=container.keys.name,
        mail_from=settings.mail_from,
        workflow_data_bucket=settings.workflow_data_bucket,
        sqs_allowed_queues=settings.sqs_allowed_queues,
        max_payload_kb=settings.max_payload_kb,
        webhook_max_body_kb=settings.webhook_max_body_kb,
    )
