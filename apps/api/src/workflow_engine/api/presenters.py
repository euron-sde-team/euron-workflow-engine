"""Domain objects to response models. Pure functions, no database access."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from workflow_engine.engine.definition import WorkflowDefinition, checksum
from workflow_engine.engine.validation import Issue
from workflow_engine.models import Credential, Workspace
from workflow_engine.nodes.base import NodeType
from workflow_engine.schemas.catalog import NodeTypeOut, RetryOut
from workflow_engine.schemas.credentials import CredentialOut
from workflow_engine.schemas.workflows import (
    IssueOut,
    LastExecution,
    TriggerOut,
    WorkflowOut,
    WorkflowStatsOut,
    WorkflowSummaryOut,
)
from workflow_engine.services.triggers import summarize, trigger_nodes, webhook_url
from workflow_engine.services.workflows import WorkflowView


def issue_out(issue: Issue) -> IssueOut:
    return IssueOut.model_validate(issue.to_json())


def _definition(raw: dict[str, Any]) -> WorkflowDefinition | None:
    try:
        return WorkflowDefinition.model_validate(raw)
    except ValidationError:
        return None


def workflow_summary(view: WorkflowView) -> WorkflowSummaryOut:
    workflow, stats = view.workflow, view.stats
    draft = _definition(workflow.draft)
    finished = stats.succeeded + stats.failed
    changed = view.published is None or draft is None or checksum(draft) != view.published.checksum
    fire_times = [t.next_fire_at for t in view.triggers if t.next_fire_at is not None]
    return WorkflowSummaryOut(
        id=workflow.id,
        name=workflow.name,
        description=workflow.description,
        tags=workflow.tags,
        active=workflow.active,
        published_version=view.published.number if view.published else None,
        has_unpublished_changes=changed,
        trigger_kinds=sorted(
            {n.type.removeprefix("trigger.") for n in trigger_nodes(draft)} if draft else set()
        ),
        concurrency_limit=workflow.concurrency_limit,
        timeout_s=workflow.timeout_s,
        template_slug=workflow.template_slug,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
        last_execution=(
            LastExecution(
                id=stats.last_execution_id, status=stats.last_status, created_at=stats.last_at
            )
            if stats.last_execution_id and stats.last_status and stats.last_at
            else None
        ),
        stats_7d=WorkflowStatsOut(
            total=stats.total,
            succeeded=stats.succeeded,
            failed=stats.failed,
            success_rate=round(stats.succeeded / finished, 4) if finished else None,
        ),
        next_run_at=min(fire_times) if fire_times else None,
    )


def workflow_detail(view: WorkflowView, workspace: Workspace, hooks_base: str) -> WorkflowOut:
    summary = workflow_summary(view)
    draft = _definition(view.workflow.draft)
    indexed = {t.node_id: t for t in view.triggers}
    triggers: list[TriggerOut] = []
    for node in trigger_nodes(draft) if draft else []:
        row = indexed.get(node.id)
        is_hook = node.type == "trigger.webhook"
        path = str(node.config.get("path", "")) if is_hook else ""
        triggers.append(
            TriggerOut(
                node_id=node.id,
                kind=node.type.removeprefix("trigger."),
                summary=summarize(node),
                next_fire_at=row.next_fire_at if row else None,
                url=webhook_url(hooks_base, workspace.slug, path) if is_hook and path else None,
                method=str(node.config.get("method", "POST")) if is_hook else None,
            )
        )
    return WorkflowOut(
        **summary.model_dump(),
        draft=view.workflow.draft,
        draft_revision=view.workflow.draft_revision,
        draft_updated_at=view.workflow.draft_updated_at,
        triggers=triggers,
        issues=[issue_out(i) for i in view.issues or []],
    )


def node_type_out(node: NodeType) -> NodeTypeOut:
    retry = node.default_retry
    return NodeTypeOut(
        type=node.type,
        name=node.name,
        category=node.category,
        description=node.description,
        icon=node.icon,
        is_trigger=node.is_trigger,
        inputs=list(node.inputs),
        ports=list(node.ports),
        port_labels=dict(node.port_labels),
        dynamic_ports=node.dynamic_ports is not None,
        side_effects=node.side_effects,
        default_retry=RetryOut(
            max_attempts=retry.max_attempts,
            initial_delay_ms=retry.initial_delay_ms,
            max_delay_ms=retry.max_delay_ms,
            multiplier=retry.multiplier,
            jitter=retry.jitter,
        ),
        default_timeout_s=node.default_timeout_s,
        template_fields=sorted(node.template_fields),
        credential_fields={k: sorted(v) for k, v in node.credential_fields.items()},
        config_schema=node.config_schema(),
        sample_output=node.sample_output,
    )


def credential_out(credential: Credential, used_by: list[str]) -> CredentialOut:
    return CredentialOut(
        id=credential.id,
        name=credential.name,
        type=credential.type,
        description=credential.description,
        public_fields=credential.public_fields,
        secret_fields=list(credential.secret_fields),
        key_provider=credential.key_provider,
        version=credential.version,
        used_by=used_by,
        created_at=credential.created_at,
        updated_at=credential.updated_at,
        last_used_at=credential.last_used_at,
    )
