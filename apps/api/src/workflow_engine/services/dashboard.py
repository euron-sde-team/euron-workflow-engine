"""The dashboard: success rate, volume, slow and busy workflows, failures, queue, workers.

Computed from indexed aggregates over one time window and cached in Redis for 15 seconds
per workspace and window, so a wall of open dashboards costs one set of queries.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from workflow_engine.repositories.dashboard import DashboardRepository, rate
from workflow_engine.repositories.executions import DeadLetterRepository
from workflow_engine.repositories.workflows import TriggerRepository
from workflow_engine.runtime.presence import live_workers
from workflow_engine.schemas.dashboard import (
    DashboardOut,
    QueueOut,
    RecentFailure,
    Totals,
    UpcomingRun,
    VolumeBucket,
    Window,
    WorkerOut,
    WorkflowTiming,
    WorkflowVolume,
)
from workflow_engine.services.container import Container

CACHE_TTL_S = 15
WINDOWS: dict[str, tuple[timedelta, str]] = {
    "24h": (timedelta(hours=24), "hour"),
    "7d": (timedelta(days=7), "day"),
    "14d": (timedelta(days=14), "day"),
    "30d": (timedelta(days=30), "day"),
}


def buckets(now: datetime, window: str, zone: ZoneInfo) -> list[datetime]:
    """Bucket starts (naive local time) covering the window, oldest first."""
    span, unit = WINDOWS[window]
    local_now = now.astimezone(zone).replace(tzinfo=None)
    if unit == "hour":
        end = local_now.replace(minute=0, second=0, microsecond=0)
        count = int(span / timedelta(hours=1))
        return [end - timedelta(hours=i) for i in reversed(range(count))]
    end = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    count = span.days
    return [end - timedelta(days=i) for i in reversed(range(count))]


class DashboardService:
    def __init__(self, container: Container, session: AsyncSession) -> None:
        self.c = container
        self.session = session
        self.repo = DashboardRepository(session)

    async def build(self, workspace_id: uuid.UUID, timezone: str, window: Window) -> DashboardOut:
        cache_key = f"wfe:dash:{workspace_id}:{window}:{timezone}"
        try:
            cached = await self.c.redis.get(cache_key)
            if cached:
                return DashboardOut.model_validate_json(cached)
        except RedisError:
            cached = None
        result = await self._compute(workspace_id, timezone, window)
        with contextlib.suppress(RedisError):
            await self.c.redis.set(cache_key, result.model_dump_json(), ex=CACHE_TTL_S)
        return result

    async def _compute(
        self, workspace_id: uuid.UUID, timezone: str, window: Window
    ) -> DashboardOut:
        now = datetime.now(UTC)
        zone = ZoneInfo(timezone)
        unit = WINDOWS[window][1]
        starts = buckets(now, window, zone)
        since_local = starts[0]
        since = since_local.replace(tzinfo=zone).astimezone(UTC)
        counts = await self.repo.status_counts(workspace_id, since)
        succeeded, failed = counts.get("succeeded", 0), counts.get("failed", 0)
        cancelled = counts.get("cancelled", 0)
        in_progress = sum(counts.get(s, 0) for s in ("queued", "running", "waiting"))
        grid = {
            start: {"succeeded": 0, "failed": 0, "cancelled": 0, "in_progress": 0}
            for start in starts
        }
        for bucket, status, count in await self.repo.volume(workspace_id, since, unit, timezone):
            key = bucket.replace(tzinfo=None)
            if key in grid:
                field = status if status in ("succeeded", "failed", "cancelled") else "in_progress"
                grid[key][field] += count
        label_format = "%H:00" if unit == "hour" else "%b %d"
        p50, p95 = await self.repo.durations(workspace_id, since)
        letters = await DeadLetterRepository(self.session).open_count(workspace_id)
        total_workflows, active = await self.repo.workflow_counts(workspace_id)
        upcoming = await TriggerRepository(self.session).upcoming(workspace_id, 5)
        workers = [
            WorkerOut(
                id=str(w.get("id")),
                hostname=str(w.get("hostname", "")),
                busy=int(w.get("busy", 0)),
                concurrency=int(w.get("concurrency", 0)),
                leader=bool(w.get("leader")),
                version=str(w.get("version", "")),
                seen_at=datetime.fromisoformat(str(w.get("seen_at"))),
            )
            for w in await live_workers(self.c.redis)
        ]
        return DashboardOut(
            window=window,
            timezone=timezone,
            generated_at=now,
            totals=Totals(
                total=sum(counts.values()),
                succeeded=succeeded,
                failed=failed,
                cancelled=cancelled,
                in_progress=in_progress,
            ),
            success_rate=rate(succeeded, succeeded + failed),
            p50_ms=p50,
            p95_ms=p95,
            volume=[
                VolumeBucket(
                    start=start.replace(tzinfo=zone).astimezone(UTC),
                    label=start.strftime(label_format),
                    **grid[start],
                )
                for start in starts
            ],
            slowest=[
                WorkflowTiming(workflow_id=w, name=n, runs=r, p95_ms=p, avg_ms=a)
                for w, n, r, p, a in await self.repo.slowest(workspace_id, since, 5)
            ],
            busiest=[
                WorkflowVolume(
                    workflow_id=w,
                    name=n,
                    runs=r,
                    failed=f,
                    failure_rate=round(f / r, 4) if r else 0.0,
                )
                for w, n, r, f in await self.repo.busiest(workspace_id, since, 5)
            ],
            recent_failures=[
                RecentFailure(
                    execution_id=e.id,
                    workflow_id=e.workflow_id,
                    workflow_name=name,
                    code=(e.error or {}).get("code"),
                    message=(e.error or {}).get("message"),
                    node_id=(e.error or {}).get("node_id"),
                    finished_at=e.finished_at,
                )
                for e, name in await self.repo.recent_failures(workspace_id, 5)
            ],
            queue=QueueOut(**await self.repo.queue(workspace_id, now)),
            dead_letters_open=letters,
            workflows=total_workflows,
            active_workflows=active,
            workers=workers,
            upcoming=[
                UpcomingRun(
                    workflow_id=t.workflow_id,
                    workflow_name=name,
                    node_id=t.node_id,
                    kind=t.kind,
                    next_fire_at=t.next_fire_at,
                )
                for t, name in upcoming
                if t.next_fire_at is not None
            ],
        )
