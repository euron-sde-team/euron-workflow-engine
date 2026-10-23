"""The trigger index: what an active workflow's published version listens for.

Webhook ingress, the event bus and the scheduler never parse definitions; they read
`workflow_triggers`, rebuilt here whenever a workflow is published or (de)activated.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from workflow_engine.core.errors import ConflictError
from workflow_engine.engine import cron
from workflow_engine.engine.definition import NodeSpec, WorkflowDefinition
from workflow_engine.models import Workflow, WorkflowTrigger
from workflow_engine.nodes.triggers import CronTriggerConfig, IntervalTriggerConfig
from workflow_engine.repositories.workflows import TriggerRepository, WorkflowRepository

INDEXED_KINDS = {
    "trigger.webhook": "webhook",
    "trigger.cron": "cron",
    "trigger.interval": "interval",
    "trigger.event": "event",
}


def trigger_nodes(definition: WorkflowDefinition) -> list[NodeSpec]:
    return [n for n in definition.nodes if n.type.startswith("trigger.")]


def webhook_url(hooks_base: str, workspace_slug: str, path: str) -> str:
    return f"{hooks_base}/hooks/{workspace_slug}/{path}"


def summarize(node: NodeSpec) -> str:
    config = node.config
    match node.type:
        case "trigger.manual":
            return "Run manually or through the API"
        case "trigger.webhook":
            auth = {"hmac_sha256": "HMAC-signed", "bearer": "token", "none": "unauthenticated"}
            return f"{config.get('method', 'POST')} webhook, {auth.get(config.get('auth', ''), '')}"
        case "trigger.cron":
            try:
                schedule = cron.parse(
                    str(config.get("expression", "")), str(config.get("timezone", "UTC"))
                )
            except cron.CronError:
                return "Schedule (invalid expression)"
            return f"{cron.describe(schedule)} ({schedule.timezone})"
        case "trigger.interval":
            return f"Every {config.get('every', '?')} {config.get('unit', 'minutes')}"
        case "trigger.event":
            return f"On event {config.get('event', '?')}"
    return node.name


def next_fire(node: NodeSpec, now: datetime) -> datetime | None:
    if node.type == "trigger.cron":
        config = CronTriggerConfig.model_validate(node.config)
        return cron.parse(config.expression, config.timezone).next_after(now)
    if node.type == "trigger.interval":
        interval = IntervalTriggerConfig.model_validate(node.config)
        return now + timedelta(seconds=interval.seconds)
    return None


class TriggerIndex:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.triggers = TriggerRepository(session)

    async def check_webhook_paths(
        self, workflow: Workflow, definition: WorkflowDefinition, workspace_slug: str
    ) -> None:
        seen: set[str] = set()
        for node in trigger_nodes(definition):
            if node.type != "trigger.webhook" or node.disabled:
                continue
            path = str(node.config.get("path", ""))
            if path in seen:
                raise ConflictError(
                    f"Two webhook triggers in this workflow use the path '{path}'.",
                    code="webhook_path_taken",
                )
            seen.add(path)
            owner = await self.triggers.webhook_owner(workflow.workspace_id, path)
            if owner is not None and owner.workflow_id != workflow.id:
                other = await WorkflowRepository(self.session).get(
                    workflow.workspace_id, owner.workflow_id
                )
                raise ConflictError(
                    f"/hooks/{workspace_slug}/{path} is already used by the active workflow "
                    f"'{other.name if other else 'another workflow'}'.",
                    code="webhook_path_taken",
                )

    async def rebuild(
        self,
        workflow: Workflow,
        version_id: uuid.UUID,
        definition: WorkflowDefinition,
        now: datetime,
    ) -> list[WorkflowTrigger]:
        """Replace the workflow's rows; unchanged schedules keep their next fire time."""
        existing = {t.node_id: t for t in await self.triggers.for_workflow(workflow.id)}
        rows: list[WorkflowTrigger] = []
        for node in trigger_nodes(definition):
            kind = INDEXED_KINDS.get(node.type)
            if kind is None or node.disabled:
                continue
            config: dict[str, Any] = dict(node.config)
            row = WorkflowTrigger(
                workspace_id=workflow.workspace_id,
                workflow_id=workflow.id,
                version_id=version_id,
                node_id=node.id,
                kind=kind,
                config=config,
            )
            previous = existing.get(node.id)
            if kind == "webhook":
                row.webhook_path = str(config["path"])
                row.webhook_method = str(config.get("method", "POST"))
            elif kind == "event":
                row.event_name = str(config["event"])
            elif kind == "cron":
                row.cron_expression = str(config["expression"])
                row.timezone = str(config.get("timezone", "UTC"))
                same = previous is not None and (
                    previous.cron_expression == row.cron_expression
                    and previous.timezone == row.timezone
                )
                row.next_fire_at = (
                    previous.next_fire_at if same and previous else next_fire(node, now)
                )
                row.last_fired_at = previous.last_fired_at if same and previous else None
            else:
                row.interval_s = IntervalTriggerConfig.model_validate(config).seconds
                same = previous is not None and previous.interval_s == row.interval_s
                row.next_fire_at = (
                    previous.next_fire_at if same and previous else next_fire(node, now)
                )
                row.last_fired_at = previous.last_fired_at if same and previous else None
            rows.append(row)
        await self.triggers.replace(workflow.id, rows)
        return rows

    async def clear(self, workflow_id: uuid.UUID) -> None:
        await self.triggers.clear(workflow_id)
