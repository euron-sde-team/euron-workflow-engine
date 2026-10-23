from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from workflow_engine.schemas.common import ApiModel

Window = Literal["24h", "7d", "14d", "30d"]


class Totals(ApiModel):
    total: int
    succeeded: int
    failed: int
    cancelled: int
    in_progress: int


class VolumeBucket(ApiModel):
    start: datetime
    label: str
    succeeded: int
    failed: int
    cancelled: int
    in_progress: int


class WorkflowTiming(ApiModel):
    workflow_id: uuid.UUID
    name: str
    runs: int
    p95_ms: int
    avg_ms: int


class WorkflowVolume(ApiModel):
    workflow_id: uuid.UUID
    name: str
    runs: int
    failed: int
    failure_rate: float


class RecentFailure(ApiModel):
    execution_id: uuid.UUID
    workflow_id: uuid.UUID
    workflow_name: str
    code: str | None
    message: str | None
    node_id: str | None
    finished_at: datetime | None


class QueueOut(ApiModel):
    executions_queued: int
    steps_ready: int
    steps_running: int
    steps_waiting: int


class WorkerOut(ApiModel):
    id: str
    hostname: str
    busy: int
    concurrency: int
    leader: bool
    version: str
    seen_at: datetime


class UpcomingRun(ApiModel):
    workflow_id: uuid.UUID
    workflow_name: str
    node_id: str
    kind: str
    next_fire_at: datetime


class DashboardOut(ApiModel):
    window: Window
    timezone: str
    generated_at: datetime
    totals: Totals
    success_rate: float | None
    p50_ms: int | None
    p95_ms: int | None
    volume: list[VolumeBucket]
    slowest: list[WorkflowTiming]
    busiest: list[WorkflowVolume]
    recent_failures: list[RecentFailure]
    queue: QueueOut
    dead_letters_open: int
    workflows: int
    active_workflows: int
    workers: list[WorkerOut]
    upcoming: list[UpcomingRun]
