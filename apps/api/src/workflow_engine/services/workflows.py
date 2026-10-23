"""Workflows: drafts, validation, publishing, activation, versions, import and export."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import orjson
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from workflow_engine.core.errors import ConflictError, NotFoundError, UnprocessableError
from workflow_engine.engine.definition import (
    MAX_DEFINITION_BYTES,
    WorkflowDefinition,
    checksum,
    empty_definition,
)
from workflow_engine.engine.validation import Issue, errors, validate
from workflow_engine.models import Workflow, WorkflowTrigger, WorkflowVersion, Workspace
from workflow_engine.models.enums import VersionKind
from workflow_engine.repositories.credentials import CredentialRepository
from workflow_engine.repositories.workflows import (
    TriggerRepository,
    VersionRepository,
    WorkflowRepository,
    WorkflowStats,
)
from workflow_engine.services import audit, gallery, portability
from workflow_engine.services.container import Container
from workflow_engine.services.principal import Principal
from workflow_engine.services.triggers import TriggerIndex
from workflow_engine.services.workspaces import workspace_settings


@dataclass(frozen=True, slots=True)
class WorkflowView:
    workflow: Workflow
    published: WorkflowVersion | None
    triggers: list[WorkflowTrigger]
    stats: WorkflowStats
    issues: list[Issue] | None = None


def parse_definition(raw: dict[str, Any]) -> WorkflowDefinition:
    if len(orjson.dumps(raw)) > MAX_DEFINITION_BYTES:
        raise UnprocessableError(
            f"The workflow is larger than {MAX_DEFINITION_BYTES // 1024} KB.", code="too_large"
        )
    try:
        return WorkflowDefinition.model_validate(raw)
    except ValidationError as exc:
        details = [
            {"field": ".".join(str(p) for p in e.get("loc", ())), "message": e.get("msg")}
            for e in exc.errors()
        ]
        raise UnprocessableError(
            "The workflow definition is malformed.", code="invalid_definition", details=details
        ) from exc


def clean_tags(tags: list[str]) -> list[str]:
    cleaned = []
    for tag in tags:
        value = "-".join(tag.strip().lower().split())[:32]
        if value and value not in cleaned:
            cleaned.append(value)
    return cleaned[:10]


class WorkflowService:
    def __init__(self, container: Container, session: AsyncSession) -> None:
        self.c = container
        self.session = session
        self.workflows = WorkflowRepository(session)
        self.versions = VersionRepository(session)
        self.triggers = TriggerRepository(session)
        self.index = TriggerIndex(session)

    # Reading -------------------------------------------------------------------------

    async def get(self, workspace_id: uuid.UUID, workflow_id: uuid.UUID) -> Workflow:
        workflow = await self.workflows.get(workspace_id, workflow_id)
        if workflow is None:
            raise NotFoundError("Workflow not found.")
        return workflow

    async def views(self, workflows: list[Workflow]) -> list[WorkflowView]:
        """Published versions, trigger rows and 7-day stats for a page: three queries."""
        ids = [w.id for w in workflows]
        published_ids = [w.published_version_id for w in workflows if w.published_version_id]
        published = {v.id: v for v in await self.versions.many(published_ids)}
        rows = await self.triggers.for_workflows(ids)
        by_workflow: dict[uuid.UUID, list[WorkflowTrigger]] = {}
        for row in rows:
            by_workflow.setdefault(row.workflow_id, []).append(row)
        stats = await self.workflows.stats(ids, datetime.now(UTC) - timedelta(days=7))
        return [
            WorkflowView(
                workflow=w,
                published=published.get(w.published_version_id) if w.published_version_id else None,
                triggers=by_workflow.get(w.id, []),
                stats=stats.get(w.id, WorkflowStats()),
            )
            for w in workflows
        ]

    async def view(self, workspace_id: uuid.UUID, workflow_id: uuid.UUID) -> WorkflowView:
        workflow = await self.get(workspace_id, workflow_id)
        (base,) = await self.views([workflow])
        issues = await self.issues(workspace_id, workflow.draft)
        return WorkflowView(base.workflow, base.published, base.triggers, base.stats, issues)

    async def page(
        self,
        workspace_id: uuid.UUID,
        *,
        search: str | None,
        tag: str | None,
        active: bool | None,
        limit: int,
        offset: int,
    ) -> tuple[list[WorkflowView], int]:
        rows, total = await self.workflows.page(
            workspace_id, search=search, tag=tag, active=active, limit=limit, offset=offset
        )
        return await self.views(rows), total

    async def issues(self, workspace_id: uuid.UUID, raw: dict[str, Any]) -> list[Issue]:
        try:
            definition = WorkflowDefinition.model_validate(raw)
        except ValidationError as exc:
            return [
                Issue(
                    "error",
                    "invalid_definition",
                    str(e.get("msg", "")),
                    field=".".join(str(p) for p in e.get("loc", ())),
                )
                for e in exc.errors()
            ]
        credentials = await CredentialRepository(self.session).types_by_id(workspace_id)
        return validate(definition, self.c.registry, credentials=credentials)

    # Writing -------------------------------------------------------------------------

    async def _unique_name(self, workspace_id: uuid.UUID, name: str) -> str:
        base = name.strip()[:110]
        taken = await self.workflows.names_like(workspace_id, base)
        if base.lower() not in taken:
            return base
        for number in range(2, 1000):
            candidate = f"{base} ({number})"
            if candidate.lower() not in taken:
                return candidate
        raise ConflictError("Too many workflows share that name.")

    async def create(
        self,
        workspace: Workspace,
        principal: Principal,
        *,
        name: str,
        description: str = "",
        tags: list[str] | None = None,
        definition: dict[str, Any] | None = None,
        template_slug: str | None = None,
        unique_name: bool = False,
        audit_action: str = "workflow.created",
    ) -> Workflow:
        if unique_name:
            name = await self._unique_name(workspace.id, name)
        elif await self.workflows.by_name(workspace.id, name.strip()):
            raise ConflictError("A workflow with that name already exists.")
        parsed = parse_definition(definition) if definition is not None else empty_definition()
        workflow = await self.workflows.add(
            Workflow(
                workspace_id=workspace.id,
                name=name.strip(),
                description=description.strip(),
                tags=clean_tags(tags or []),
                draft=parsed.model_dump(mode="json"),
                draft_updated_by=principal.user_id,
                timeout_s=workspace_settings(workspace).default_timeout_s,
                template_slug=template_slug,
                created_by=principal.user_id,
            )
        )
        await audit.record(
            self.session,
            workspace_id=workspace.id,
            principal=principal,
            action=audit_action,
            target_type="workflow",
            target_id=workflow.id,
            details={
                "name": workflow.name,
                **({"template": template_slug} if template_slug else {}),
            },
        )
        await self.session.commit()
        return workflow

    async def create_from_template(
        self, workspace: Workspace, principal: Principal, slug: str, name: str | None = None
    ) -> tuple[Workflow, list[dict[str, str]]]:
        found = gallery.template(slug)
        definition, missing = await self._internalize(
            workspace.id, found.definition, list(found.credentials)
        )
        workflow = await self.create(
            workspace,
            principal,
            name=name or found.name,
            description=found.summary,
            tags=list(found.tags),
            definition=definition,
            template_slug=slug,
            unique_name=True,
        )
        return workflow, missing

    async def _internalize(
        self,
        workspace_id: uuid.UUID,
        definition: dict[str, Any],
        declared: list[dict[str, str]] | None,
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        rows = await CredentialRepository(self.session).all(workspace_id)
        lookup = {(c.name.lower(), c.type): str(c.id) for c in rows}
        return portability.internalize(definition, self.c.registry, lookup, declared)

    async def update(
        self,
        workspace_id: uuid.UUID,
        principal: Principal,
        workflow_id: uuid.UUID,
        *,
        name: str | None,
        description: str | None,
        tags: list[str] | None,
        concurrency_limit: int | None,
        clear_concurrency_limit: bool,
        timeout_s: int | None,
    ) -> Workflow:
        workflow = await self.get(workspace_id, workflow_id)
        changed: dict[str, Any] = {}
        if name is not None and name.strip() != workflow.name:
            clash = await self.workflows.by_name(workspace_id, name.strip())
            if clash is not None and clash.id != workflow.id:
                raise ConflictError("A workflow with that name already exists.")
            workflow.name = name.strip()
            changed["name"] = workflow.name
        if description is not None and description.strip() != workflow.description:
            workflow.description = description.strip()
            changed["description"] = True
        if tags is not None and clean_tags(tags) != workflow.tags:
            workflow.tags = clean_tags(tags)
            changed["tags"] = workflow.tags
        if clear_concurrency_limit and workflow.concurrency_limit is not None:
            workflow.concurrency_limit = None
            changed["concurrency_limit"] = None
        elif concurrency_limit is not None and concurrency_limit != workflow.concurrency_limit:
            workflow.concurrency_limit = concurrency_limit
            changed["concurrency_limit"] = concurrency_limit
        if timeout_s is not None and timeout_s != workflow.timeout_s:
            workflow.timeout_s = timeout_s
            changed["timeout_s"] = timeout_s
        if changed:
            await audit.record(
                self.session,
                workspace_id=workspace_id,
                principal=principal,
                action="workflow.updated",
                target_type="workflow",
                target_id=workflow.id,
                details=changed,
            )
            await self.session.commit()
        return workflow

    async def save_draft(
        self,
        workspace_id: uuid.UUID,
        principal: Principal,
        workflow_id: uuid.UUID,
        raw: dict[str, Any],
        revision: int,
    ) -> tuple[Workflow, list[Issue]]:
        definition = parse_definition(raw)
        await self.get(workspace_id, workflow_id)
        saved = await self.workflows.save_draft(
            workspace_id,
            workflow_id,
            definition=definition.model_dump(mode="json"),
            expected_revision=revision,
            user_id=principal.user_id,
        )
        if saved is None:
            raise ConflictError(
                "Someone saved this workflow after you opened it. Reload to see their changes.",
                code="stale_draft",
            )
        await self.session.commit()
        workflow = await self.get(workspace_id, workflow_id)
        await self.session.refresh(workflow)
        return workflow, await self.issues(workspace_id, workflow.draft)

    async def publish(
        self,
        workspace: Workspace,
        principal: Principal,
        workflow_id: uuid.UUID,
        *,
        note: str,
        activate: bool,
    ) -> WorkflowVersion:
        workflow = await self.workflows.get_for_update(workspace.id, workflow_id)
        if workflow is None:
            raise NotFoundError("Workflow not found.")
        definition = parse_definition(workflow.draft)
        problems = errors(await self.issues(workspace.id, workflow.draft))
        if problems:
            raise UnprocessableError(
                "Fix the problems in the workflow before publishing it.",
                code="invalid_workflow",
                details=[p.to_json() for p in problems],
            )
        digest = checksum(definition)
        current = (
            await self.session.get(WorkflowVersion, workflow.published_version_id)
            if workflow.published_version_id
            else None
        )
        if current is not None and current.checksum == digest:
            if not activate:
                return current
            version = current
        else:
            version = await self.versions.add(
                WorkflowVersion(
                    workspace_id=workspace.id,
                    workflow_id=workflow.id,
                    kind=VersionKind.PUBLISHED,
                    number=await self.versions.next_number(workflow.id),
                    definition=definition.model_dump(mode="json"),
                    checksum=digest,
                    note=note.strip(),
                    created_by=principal.user_id,
                )
            )
            workflow.published_version_id = version.id
            await audit.record(
                self.session,
                workspace_id=workspace.id,
                principal=principal,
                action="workflow.published",
                target_type="workflow",
                target_id=workflow.id,
                details={"version": version.number, "note": version.note},
            )
        if workflow.active or activate:
            await self._activate(workspace, principal, workflow, version, definition)
        await self.session.commit()
        return version

    async def _activate(
        self,
        workspace: Workspace,
        principal: Principal,
        workflow: Workflow,
        version: WorkflowVersion,
        definition: WorkflowDefinition,
    ) -> None:
        await self.index.check_webhook_paths(workflow, definition, workspace.slug)
        await self.index.rebuild(workflow, version.id, definition, datetime.now(UTC))
        if not workflow.active:
            workflow.active = True
            workflow.activated_at = datetime.now(UTC)
            await audit.record(
                self.session,
                workspace_id=workspace.id,
                principal=principal,
                action="workflow.activated",
                target_type="workflow",
                target_id=workflow.id,
                details={"version": version.number},
            )

    async def activate(
        self, workspace: Workspace, principal: Principal, workflow_id: uuid.UUID
    ) -> Workflow:
        workflow = await self.workflows.get_for_update(workspace.id, workflow_id)
        if workflow is None:
            raise NotFoundError("Workflow not found.")
        if workflow.published_version_id is None:
            raise UnprocessableError(
                "Publish the workflow before activating it.", code="not_published"
            )
        version = await self.session.get(WorkflowVersion, workflow.published_version_id)
        if version is None:  # pragma: no cover - guarded by the foreign key
            raise NotFoundError("The published version is missing.")
        await self._activate(
            workspace,
            principal,
            workflow,
            version,
            WorkflowDefinition.model_validate(version.definition),
        )
        await self.session.commit()
        return workflow

    async def deactivate(
        self, workspace_id: uuid.UUID, principal: Principal, workflow_id: uuid.UUID
    ) -> Workflow:
        workflow = await self.workflows.get_for_update(workspace_id, workflow_id)
        if workflow is None:
            raise NotFoundError("Workflow not found.")
        if workflow.active:
            await self.index.clear(workflow.id)
            workflow.active = False
            await audit.record(
                self.session,
                workspace_id=workspace_id,
                principal=principal,
                action="workflow.deactivated",
                target_type="workflow",
                target_id=workflow.id,
            )
            await self.session.commit()
        return workflow

    async def versions_of(
        self, workspace_id: uuid.UUID, workflow_id: uuid.UUID
    ) -> list[WorkflowVersion]:
        await self.get(workspace_id, workflow_id)
        return await self.versions.published(workflow_id)

    async def version(
        self, workspace_id: uuid.UUID, workflow_id: uuid.UUID, number: int
    ) -> WorkflowVersion:
        await self.get(workspace_id, workflow_id)
        version = await self.versions.by_number(workflow_id, number)
        if version is None:
            raise NotFoundError("Version not found.")
        return version

    async def restore(
        self, workspace_id: uuid.UUID, principal: Principal, workflow_id: uuid.UUID, number: int
    ) -> Workflow:
        version = await self.version(workspace_id, workflow_id, number)
        workflow = await self.get(workspace_id, workflow_id)
        saved = await self.workflows.save_draft(
            workspace_id,
            workflow_id,
            definition=version.definition,
            expected_revision=workflow.draft_revision,
            user_id=principal.user_id,
        )
        if saved is None:
            raise ConflictError("The draft changed while restoring. Try again.", code="stale_draft")
        await audit.record(
            self.session,
            workspace_id=workspace_id,
            principal=principal,
            action="workflow.restored",
            target_type="workflow",
            target_id=workflow_id,
            details={"version": number},
        )
        await self.session.commit()
        await self.session.refresh(workflow)
        return workflow

    async def duplicate(
        self, workspace: Workspace, principal: Principal, workflow_id: uuid.UUID
    ) -> Workflow:
        source = await self.get(workspace.id, workflow_id)
        return await self.create(
            workspace,
            principal,
            name=f"{source.name} (copy)",
            description=source.description,
            tags=list(source.tags),
            definition=source.draft,
            template_slug=source.template_slug,
            unique_name=True,
            audit_action="workflow.duplicated",
        )

    async def delete(
        self, workspace_id: uuid.UUID, principal: Principal, workflow_id: uuid.UUID
    ) -> None:
        workflow = await self.get(workspace_id, workflow_id)
        await audit.record(
            self.session,
            workspace_id=workspace_id,
            principal=principal,
            action="workflow.deleted",
            target_type="workflow",
            target_id=workflow_id,
            details={"name": workflow.name},
        )
        await self.session.delete(workflow)
        await self.session.commit()

    # Portability ---------------------------------------------------------------------

    async def export(
        self, workspace_id: uuid.UUID, workflow_id: uuid.UUID, *, published: bool
    ) -> dict[str, Any]:
        workflow = await self.get(workspace_id, workflow_id)
        definition = workflow.draft
        if published:
            if workflow.published_version_id is None:
                raise UnprocessableError("This workflow has no published version yet.")
            version = await self.session.get(WorkflowVersion, workflow.published_version_id)
            definition = version.definition if version else definition
        rows = await CredentialRepository(self.session).all(workspace_id)
        portable, needed = portability.externalize(
            definition, self.c.registry, {str(c.id): (c.name, c.type) for c in rows}
        )
        return {
            "format": "euron-workflow",
            "format_version": 1,
            "name": workflow.name,
            "description": workflow.description,
            "tags": workflow.tags,
            "settings": {
                "concurrency_limit": workflow.concurrency_limit,
                "timeout_s": workflow.timeout_s,
            },
            "definition": portable,
            "credentials": needed,
            "exported_at": datetime.now(UTC).isoformat(),
        }

    async def import_document(
        self, workspace: Workspace, principal: Principal, document: dict[str, Any]
    ) -> tuple[Workflow, list[dict[str, str]]]:
        if document.get("format") != "euron-workflow" or document.get("format_version") != 1:
            raise UnprocessableError(
                "This is not a Euron WorkflowEngine export (format euron-workflow, version 1).",
                code="invalid_export",
            )
        raw = document.get("definition")
        if not isinstance(raw, dict):
            raise UnprocessableError("The export has no definition.", code="invalid_export")
        declared = [c for c in document.get("credentials") or [] if isinstance(c, dict)]
        definition, missing = await self._internalize(workspace.id, raw, declared)
        workflow = await self.create(
            workspace,
            principal,
            name=str(document.get("name") or "Imported workflow")[:120],
            description=str(document.get("description") or "")[:2000],
            tags=[str(t) for t in document.get("tags") or []],
            definition=definition,
            unique_name=True,
            audit_action="workflow.imported",
        )
        settings = document.get("settings") or {}
        limit = settings.get("concurrency_limit")
        timeout = settings.get("timeout_s")
        if isinstance(limit, int) and 1 <= limit <= 1000:
            workflow.concurrency_limit = limit
        if isinstance(timeout, int) and 10 <= timeout <= 604_800:
            workflow.timeout_s = timeout
        await self.session.commit()
        return workflow, missing
