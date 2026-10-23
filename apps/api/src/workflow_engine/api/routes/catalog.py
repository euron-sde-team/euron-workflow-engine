"""Node types, credential types, the template gallery and the cron preview."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from workflow_engine.api.deps import ContainerDep, PrincipalDep
from workflow_engine.api.presenters import node_type_out
from workflow_engine.engine import cron
from workflow_engine.nodes.credentials import CREDENTIAL_TYPES
from workflow_engine.nodes.registry import ordered
from workflow_engine.schemas.catalog import (
    CronPreviewOut,
    CronPreviewRequest,
    NodeTypeOut,
    TemplateOut,
    TemplateSummaryOut,
)
from workflow_engine.schemas.credentials import CredentialTypeOut
from workflow_engine.services import gallery

router = APIRouter(prefix="/api/v1", tags=["catalog"])


@router.get("/node-types", summary="Every node type with its configuration schema")
async def node_types(principal: PrincipalDep) -> list[NodeTypeOut]:
    return [node_type_out(n) for n in ordered()]


@router.get("/credential-types", summary="Credential types and which of their fields are secret")
async def credential_types(principal: PrincipalDep) -> list[CredentialTypeOut]:
    return [
        CredentialTypeOut(
            type=t.type,
            name=t.name,
            description=t.description,
            icon=t.icon,
            secret_fields=sorted(t.secret_fields),
            json_schema=t.model.model_json_schema(),
        )
        for t in CREDENTIAL_TYPES.values()
    ]


def _summary(t: gallery.GalleryTemplate) -> TemplateSummaryOut:
    return TemplateSummaryOut(
        slug=t.slug,
        name=t.name,
        summary=t.summary,
        description=t.description,
        category=t.category,
        tags=list(t.tags),
        node_types=t.node_types,
        trigger_kinds=t.trigger_kinds,
        credentials=list(t.credentials),
        variables=list(t.variables),
    )


@router.get("/templates", summary="The templates gallery")
async def templates(principal: PrincipalDep) -> list[TemplateSummaryOut]:
    return [_summary(t) for t in gallery.templates().values()]


@router.get("/templates/{slug}", summary="One template with its definition")
async def template(slug: str, principal: PrincipalDep) -> TemplateOut:
    found = gallery.template(slug)
    return TemplateOut(**_summary(found).model_dump(), definition=found.definition)


@router.post("/tools/cron-preview", summary="Check a cron expression and list its next runs")
async def cron_preview(
    body: CronPreviewRequest, principal: PrincipalDep, container: ContainerDep
) -> CronPreviewOut:
    try:
        schedule = cron.parse(body.expression, body.timezone)
    except cron.CronError as exc:
        return CronPreviewOut(valid=False, error=str(exc))
    return CronPreviewOut(
        valid=True,
        description=cron.describe(schedule),
        next=schedule.upcoming(datetime.now(UTC), body.count),
    )
