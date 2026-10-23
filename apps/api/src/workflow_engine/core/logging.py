"""Structured logging: JSON lines in production, readable console output on a laptop.

Standard-library loggers (uvicorn, SQLAlchemy, botocore) are routed through the same
structlog pipeline, so every line carries the request id bound by the request middleware.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import orjson
import structlog

_SENSITIVE = ("password", "secret", "token", "authorization", "api_key", "cookie", "signature")


def _redact(_: Any, __: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    for key in list(event):
        if any(marker in key.lower() for marker in _SENSITIVE):
            event[key] = "[redacted]"
    return event


def _dumps(obj: Any, **_: Any) -> str:
    return orjson.dumps(obj, default=str).decode()


def configure_logging(level: str = "info", fmt: str = "json") -> None:
    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact,
    ]
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer(serializer=_dumps)
        if fmt == "json"
        else structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())
    )
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            renderer,
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # The request middleware writes one access line per request with the route template
    # and latency, so uvicorn's own access log would only duplicate it.
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
    for noisy in ("botocore", "boto3", "urllib3", "httpx", "httpcore", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
