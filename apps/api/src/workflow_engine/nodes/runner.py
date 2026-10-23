"""Render a node's templates, validate its configuration and run it.

Shared by the worker (durable steps) and the test-run endpoint (one node, nothing stored),
so a node behaves identically in both. Timeouts are the caller's job, because the worker
and the test endpoint enforce them differently.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import anyio
from pydantic import ValidationError

from workflow_engine.engine.templates import TemplateError, render
from workflow_engine.nodes.base import NodeContext, NodeError, NodeResult, NodeType


def render_config(
    node_type: NodeType, raw: dict[str, Any], context: dict[str, Any], now: datetime
) -> dict[str, Any]:
    rendered = dict(raw)
    for name in node_type.template_fields:
        if name in raw:
            try:
                rendered[name] = render(raw[name], context, now=now)
            except TemplateError as exc:
                raise NodeError(
                    "template_error", f"{name}: {exc}", details={"field": name}
                ) from exc
    return rendered


def _location(loc: tuple[int | str, ...]) -> str:
    path = ""
    for part in loc:
        path += f"[{part}]" if isinstance(part, int) else (f".{part}" if path else str(part))
    return path


def validate_config(node_type: NodeType, rendered: dict[str, Any]) -> Any:
    try:
        return node_type.config_model.model_validate(rendered)
    except ValidationError as exc:
        problems = [
            {
                "field": _location(tuple(error.get("loc", ()))),
                "message": str(error.get("msg", "")).removeprefix("Value error, "),
            }
            for error in exc.errors()
        ]
        first = problems[0]
        where = f"{first['field']}: " if first["field"] else ""
        raise NodeError(
            "invalid_config", f"{where}{first['message']}", details={"problems": problems}
        ) from exc


async def execute(node_type: NodeType, ctx: NodeContext) -> NodeResult:
    if node_type.run is None:
        raise NodeError("not_runnable", f"{node_type.name} starts executions; it does not run.")
    # Rendering evaluates JMESPath over the whole context: CPU work, off the event loop.
    rendered = await anyio.to_thread.run_sync(
        render_config, node_type, ctx.node.config, ctx.expression_context, ctx.now
    )
    config = validate_config(node_type, rendered)
    return await node_type.run(ctx, config)
