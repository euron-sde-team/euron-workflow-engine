"""The scheduler leader's duties, one small transaction per item.

Each sweep first reads candidate ids without locks, then handles each candidate in its
own transaction that locks the execution (or trigger) with SKIP LOCKED and re-checks the
condition. A row that a completion is holding is simply picked up on the next tick, so a
sweep never waits behind a worker and a second scheduler (during a lock handover) only
duplicates reads, never writes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import orjson
from redis.exceptions import RedisError
from sqlalchemy import select

from workflow_engine.core import metrics
from workflow_engine.core.logging import get_logger
from workflow_engine.engine import cron
from workflow_engine.engine.expressions import iso
from workflow_engine.models import ExecutionLog, Workflow, WorkflowTrigger
from workflow_engine.models.enums import ExecutionMode, ExecutionStatus, StepStatus, TriggerKind
from workflow_engine.nodes.base import NodeError
from workflow_engine.nodes.triggers import CronTriggerConfig, IntervalTriggerConfig
from workflow_engine.repositories.executions import ExecutionRepository, StepRepository
from workflow_engine.repositories.workspaces import WorkspaceRepository
from workflow_engine.services.container import Container
from workflow_engine.services.engine import Engine

log = get_logger("wfe.sweeps")
QUEUE_STATS_KEY = "wfe:stats:queue"
PRUNE_BATCH = 500


def _next_fire(trigger: WorkflowTrigger, due: datetime, now: datetime) -> datetime | None:
    """The next tick after now. Missed ticks (downtime) coalesce into the one just fired."""
    if trigger.kind == "cron":
        config = CronTriggerConfig.model_validate(trigger.config)
        return cron.parse(config.expression, config.timezone).next_after(now)
    seconds = IntervalTriggerConfig.model_validate(trigger.config).seconds
    following = due + timedelta(seconds=seconds)
    return following if following > now else now + timedelta(seconds=seconds)


async def fire_schedules(container: Container, now: datetime, limit: int = 100) -> int:
    async with container.db.session() as session:
        due_ids = list(
            (
                await session.execute(
                    select(WorkflowTrigger.id)
                    .where(
                        WorkflowTrigger.kind.in_(("cron", "interval")),
                        WorkflowTrigger.next_fire_at <= now,
                    )
                    .order_by(WorkflowTrigger.next_fire_at)
                    .limit(limit)
                )
            ).scalars()
        )
    fired = 0
    for trigger_id in due_ids:
        async with container.db.session() as session:
            engine = Engine(container, session)
            trigger = (
                await session.execute(
                    select(WorkflowTrigger)
                    .where(WorkflowTrigger.id == trigger_id)
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if trigger is None or trigger.next_fire_at is None or trigger.next_fire_at > now:
                continue
            due = trigger.next_fire_at
            workflow = await session.get(Workflow, trigger.workflow_id)
            trigger.last_fired_at = due
            trigger.next_fire_at = _next_fire(trigger, due, now)
            kind = TriggerKind.CRON if trigger.kind == "cron" else TriggerKind.INTERVAL
            overlap = str(trigger.config.get("overlap", "allow"))
            if workflow is None or not workflow.active:
                await session.commit()
                continue
            if overlap == "skip" and await engine.executions.in_progress_count(workflow.id) > 0:
                metrics.SCHEDULE_FIRES.labels(trigger.kind, "skipped_overlap").inc()
                await session.commit()
                continue
            payload = {"scheduled_for": iso(due), "fired_at": iso(now)}
            if trigger.timezone:
                payload["timezone"] = trigger.timezone
            # Admitted after commit: this transaction holds the trigger row, and publishing
            # takes the workflow row first; locking both here could deadlock.
            result = await engine.start(
                workflow=workflow,
                version_id=trigger.version_id,
                trigger_node_id=trigger.node_id,
                payload=payload,
                mode=ExecutionMode.PRODUCTION,
                trigger_kind=kind,
                idempotency_key=f"schedule:{trigger.id}:{iso(due)}",
                admit_now=False,
            )
            await engine.commit()
            metrics.SCHEDULE_FIRES.labels(
                trigger.kind, "duplicate" if result.duplicate else "fired"
            ).inc()
            fired += 0 if result.duplicate else 1
    return fired


async def wake_due(container: Container, now: datetime, limit: int = 200) -> int:
    async with container.db.session() as session:
        candidates = await StepRepository(session).due_waiting(now, limit)
    woken = 0
    for step_id, execution_id in candidates:
        async with container.db.session() as session:
            engine = Engine(container, session)
            execution = await engine.executions.lock(execution_id, skip_locked=True)
            step = await engine.steps.lock(step_id) if execution else None
            if execution is None or step is None or step.status != StepStatus.WAITING:
                continue
            step.status = StepStatus.QUEUED
            step.state = {**(step.state or {}), "resumed": True}
            step.available_at = now
            if execution.status == ExecutionStatus.WAITING:
                execution.status = ExecutionStatus.RUNNING
            engine.wake_after_commit()
            await engine.commit()
            woken += 1
    return woken


async def reap_stale(container: Container, now: datetime, limit: int = 100) -> int:
    cutoff = now - timedelta(seconds=container.settings.step_stale_s)
    async with container.db.session() as session:
        candidates = await StepRepository(session).stale(cutoff, limit)
    reaped = 0
    for step_id, execution_id in candidates:
        async with container.db.session() as session:
            engine = Engine(container, session)
            execution = await engine.executions.lock(execution_id, skip_locked=True)
            step = await engine.steps.lock(step_id) if execution else None
            if execution is None or step is None or step.status != StepStatus.RUNNING:
                continue
            if step.heartbeat_at is not None and step.heartbeat_at >= cutoff:
                continue
            worker = step.locked_by or "unknown"
            session.add(
                ExecutionLog(
                    execution_id=step.execution_id,
                    step_id=step.id,
                    workspace_id=step.workspace_id,
                    level="warn",
                    message=f"Worker {worker} stopped sending heartbeats; the step was reclaimed",
                    data={"worker": worker},
                )
            )
            if execution.status not in (ExecutionStatus.RUNNING, ExecutionStatus.WAITING):
                step.status = StepStatus.CANCELLED
                step.finished_at = now
            else:
                compiled = await engine.compiled(execution.version_id)
                await engine.record_failure(
                    execution,
                    compiled,
                    step,
                    NodeError(
                        "worker_lost",
                        f"The worker running this step ({worker}) stopped sending heartbeats.",
                        retryable=True,
                    ),
                    None,
                    allow_retry=True,
                )
            await engine.commit()
            metrics.STEPS_REAPED.inc()
            reaped += 1
    return reaped


async def enforce_deadlines(container: Container, now: datetime, limit: int = 100) -> int:
    async with container.db.session() as session:
        candidates = await ExecutionRepository(session).past_deadline(now, limit)
    failed = 0
    for execution_id in candidates:
        async with container.db.session() as session:
            engine = Engine(container, session)
            execution = await engine.executions.lock(execution_id, skip_locked=True)
            if (
                execution is None
                or execution.status not in (ExecutionStatus.RUNNING, ExecutionStatus.WAITING)
                or execution.deadline_at is None
                or execution.deadline_at >= now
            ):
                continue
            started = execution.started_at or execution.created_at
            seconds = int((execution.deadline_at - started).total_seconds())
            await engine.fail_execution(
                execution,
                None,
                {
                    "code": "execution_timeout",
                    "message": f"The execution ran longer than its {seconds} s timeout.",
                },
            )
            await engine.commit()
            failed += 1
    return failed


async def admit_queued(container: Container, limit: int = 50) -> int:
    async with container.db.session() as session:
        workflow_ids = await ExecutionRepository(session).workflows_with_queued(limit)
    admitted = 0
    for workflow_id in workflow_ids:
        async with container.db.session() as session:
            engine = Engine(container, session)
            admitted += await engine.admit(workflow_id)
            await engine.commit()
    return admitted


async def prune(container: Container, now: datetime, max_batches: int = 20) -> int:
    async with container.db.session() as session:
        workspaces = await WorkspaceRepository(session).all_ids()
    deleted = 0
    for workspace_id, retention_days in workspaces:
        cutoff = now - timedelta(days=retention_days)
        for _ in range(max_batches):
            async with container.db.session() as session:
                repo = ExecutionRepository(session)
                count = await repo.prune(workspace_id, cutoff, PRUNE_BATCH)
                count += await repo.prune_events(workspace_id, cutoff, PRUNE_BATCH)
                await session.commit()
            deleted += count
            if count == 0:
                break
    if deleted:
        log.info("pruned", rows=deleted)
    return deleted


async def queue_stats(
    container: Container, now: datetime | None = None
) -> dict[str, dict[str, int]]:
    moment = now or datetime.now(UTC)
    async with container.db.session() as session:
        steps = await StepRepository(session).status_counts()
        ready = await StepRepository(session).ready_count(moment)
        executions = await ExecutionRepository(session).status_counts()
    stats = {
        "steps": {
            "queued": steps.get("queued", 0),
            "ready": ready,
            "running": steps.get("running", 0),
            "waiting": steps.get("waiting", 0),
        },
        "executions": {
            "queued": executions.get("queued", 0),
            "running": executions.get("running", 0),
            "waiting": executions.get("waiting", 0),
        },
    }
    try:
        await container.redis.set(QUEUE_STATS_KEY, orjson.dumps(stats), ex=30)
    except RedisError:
        log.warning("queue_stats_not_published")
    for kind, states in stats.items():
        for state, count in states.items():
            metrics.QUEUE_DEPTH.labels(kind, state).set(count)
    return stats
