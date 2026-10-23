"""Test-run one node with sample data, in the API process. Nothing is stored.

Side-effect nodes really perform their action (the editor says so before running one),
except `event.emit`: a test run reports the event it would publish instead of starting
production workflows from the editor.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from workflow_engine.core.errors import UnprocessableError
from workflow_engine.engine.definition import NodeSpec
from workflow_engine.engine.expressions import iso
from workflow_engine.nodes import runner
from workflow_engine.nodes.base import NodeContext, NodeError, NodeResult
from workflow_engine.repositories.variables import VariableRepository
from workflow_engine.schemas.nodes import LogLineOut, NodeTestRequest, NodeTestResult
from workflow_engine.services.container import Container
from workflow_engine.services.engine import redact
from workflow_engine.services.node_services import RuntimeServices

MAX_TEST_TIMEOUT_S = 60


class NodeTestService:
    def __init__(self, container: Container, session: AsyncSession) -> None:
        self.c = container
        self.session = session

    async def run(self, workspace_id: uuid.UUID, body: NodeTestRequest) -> NodeTestResult:
        try:
            node = NodeSpec.model_validate({"id": "node", "name": "Node", **body.node})
        except ValidationError as exc:
            raise UnprocessableError("The node is malformed.", details=exc.errors()) from exc
        node_type = self.c.registry.get(node.type)
        if node_type is None:
            raise UnprocessableError(f"Unknown node type '{node.type}'.")
        if node_type.is_trigger:
            raise UnprocessableError("Triggers do not run; test the nodes after them.")
        env = await VariableRepository(self.session).as_dict(workspace_id)
        now = datetime.now(UTC)
        ctx = NodeContext(
            workspace_id=workspace_id,
            execution_id=None,
            step_id=None,
            node=node,
            input=body.input,
            expression_context={
                "trigger": body.trigger,
                "input": body.input,
                "steps": body.steps,
                "vars": body.vars,
                "env": env,
                "execution": {"id": None, "mode": "test", "attempt": 1},
                "now": iso(now),
            },
            now=now,
            attempt=1,
            services=RuntimeServices(self.c),
            test_run=True,
        )
        timeout = min(node.timeout_s or node_type.default_timeout_s, MAX_TEST_TIMEOUT_S)
        started = time.perf_counter()
        result: NodeResult | None = None
        error: dict[str, Any] | None = None
        try:
            async with asyncio.timeout(timeout):
                result = await runner.execute(node_type, ctx)
        except NodeError as exc:
            error = exc.to_json()
        except TimeoutError:
            error = {"code": "timeout", "message": f"The node ran longer than {timeout} s."}
        duration = int((time.perf_counter() - started) * 1000)
        logs = [
            LogLineOut(
                level=line.level,
                message=str(redact(line.message, ctx.secrets)),
                data=redact(line.data, ctx.secrets),
            )
            for line in ctx.logs
        ]
        if result is None:
            return NodeTestResult(
                status="failed", error=redact(error, ctx.secrets), logs=logs, duration_ms=duration
            )
        output: Any = result.output
        ports = list(result.ports)
        if result.loop_start is not None:
            output = {
                "items": result.loop_start.items[:20],
                "items_total": len(result.loop_start.items),
                "batch_size": result.loop_start.batch_size,
            }
            ports = ["batch"] if result.loop_start.items else ["done"]
        return NodeTestResult(
            status="succeeded",
            output=redact(output, ctx.secrets),
            ports=ports,
            vars=redact(result.vars, ctx.secrets),
            events=[{"event": name, "payload": payload} for name, payload in result.events],
            suspend_until=result.suspend_until.isoformat() if result.suspend_until else None,
            logs=logs,
            duration_ms=duration,
        )
