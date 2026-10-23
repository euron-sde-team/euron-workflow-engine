from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from workflow_engine.schemas.common import ApiModel


class ExecutionError(ApiModel):
    code: str
    message: str
    node_id: str | None = None
    step_id: str | None = None


class ExecutionSummaryOut(ApiModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    workflow_name: str
    version_id: uuid.UUID
    status: str
    mode: str
    trigger_kind: str
    trigger_node_id: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    error: ExecutionError | None = None
    resume_count: int
    retry_of_id: uuid.UUID | None = None


class StepSummaryOut(ApiModel):
    id: uuid.UUID
    node_id: str
    node_type: str
    node_name: str
    run_index: int
    scope: str
    status: str
    attempt: int
    max_attempts: int
    ports: list[str]
    error: dict[str, Any] | None = None
    available_at: datetime | None = None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None


class StepOut(StepSummaryOut):
    input: Any = None
    output: Any = None
    state: dict[str, Any] = Field(default_factory=dict)


class ExecutionOut(ExecutionSummaryOut):
    trigger_payload: Any = None
    output: Any = None
    variables: dict[str, Any] = Field(default_factory=dict)
    version_number: int | None = None
    steps: list[StepSummaryOut]
    steps_truncated: bool = False


class LogOut(ApiModel):
    id: int
    step_id: uuid.UUID | None
    level: str
    message: str
    data: dict[str, Any]
    created_at: datetime


class LogPage(ApiModel):
    items: list[LogOut]
    next_after: int | None = None


class DeadLetterOut(ApiModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    workflow_name: str
    execution_id: uuid.UUID
    step_id: uuid.UUID | None
    node_id: str
    node_name: str
    error: dict[str, Any]
    input: Any = None
    status: str
    created_at: datetime
    resolved_at: datetime | None
