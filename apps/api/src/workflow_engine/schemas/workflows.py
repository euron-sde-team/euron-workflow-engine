from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from workflow_engine.schemas.common import ApiModel

TAG = r"^[a-z0-9][a-z0-9-]{0,31}$"


class IssueOut(ApiModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    node_id: str | None = None
    field: str | None = None
    edge_id: str | None = None


class LastExecution(ApiModel):
    id: uuid.UUID
    status: str
    created_at: datetime


class WorkflowStatsOut(ApiModel):
    total: int
    succeeded: int
    failed: int
    success_rate: float | None = Field(description="Succeeded share of finished runs, 0 to 1.")


class TriggerOut(ApiModel):
    node_id: str
    kind: str
    summary: str
    next_fire_at: datetime | None = None
    url: str | None = None
    method: str | None = None


class WorkflowSummaryOut(ApiModel):
    id: uuid.UUID
    name: str
    description: str
    tags: list[str]
    active: bool
    published_version: int | None
    has_unpublished_changes: bool
    trigger_kinds: list[str]
    concurrency_limit: int | None
    timeout_s: int
    template_slug: str | None
    created_at: datetime
    updated_at: datetime
    last_execution: LastExecution | None = None
    stats_7d: WorkflowStatsOut
    next_run_at: datetime | None = None


class WorkflowOut(WorkflowSummaryOut):
    draft: dict[str, Any]
    draft_revision: int
    draft_updated_at: datetime
    triggers: list[TriggerOut]
    issues: list[IssueOut]


class WorkflowCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=10)
    template: str | None = Field(default=None, max_length=64, description="A gallery slug.")
    definition: dict[str, Any] | None = None


class WorkflowUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = Field(default=None, max_length=10)
    concurrency_limit: int | None = Field(default=None, ge=1, le=1000)
    clear_concurrency_limit: bool = False
    timeout_s: int | None = Field(default=None, ge=10, le=604_800)


class DraftSave(ApiModel):
    definition: dict[str, Any]
    revision: int = Field(ge=1, description="The draft_revision this edit started from.")


class DraftSaved(ApiModel):
    revision: int
    updated_at: datetime
    issues: list[IssueOut]


class ValidateRequest(ApiModel):
    definition: dict[str, Any] | None = Field(
        default=None, description="Validate this definition instead of the saved draft."
    )


class PublishRequest(ApiModel):
    note: str = Field(default="", max_length=500)
    activate: bool = Field(default=False, description="Also activate the workflow's triggers.")


class VersionOut(ApiModel):
    id: uuid.UUID
    number: int
    note: str
    checksum: str
    node_count: int
    created_at: datetime
    created_by_name: str | None = None
    is_current: bool = False


class VersionDetailOut(VersionOut):
    definition: dict[str, Any]


class RunRequest(ApiModel):
    payload: Any = None
    use_draft: bool = Field(
        default=False,
        description="Run the saved draft (a test run) instead of the published version.",
    )
    trigger_node: str | None = Field(default=None, max_length=48)


class RunOut(ApiModel):
    execution_id: uuid.UUID
    status: str
    duplicate: bool = False


class ExportDocument(ApiModel):
    format: Literal["euron-workflow"] = "euron-workflow"
    format_version: Literal[1] = 1
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)
    definition: dict[str, Any]
    credentials: list[dict[str, str]] = Field(
        default_factory=list, description="The credentials the workflow needs, by name and type."
    )
    exported_at: datetime | None = None


class ImportResult(ApiModel):
    workflow: WorkflowOut
    unresolved_credentials: list[dict[str, str]]
