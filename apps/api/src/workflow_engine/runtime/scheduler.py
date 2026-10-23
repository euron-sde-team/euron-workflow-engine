"""The scheduler loop. Every worker runs it; only the Redis leader does the work."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from workflow_engine.core import metrics
from workflow_engine.core.logging import get_logger
from workflow_engine.runtime.clock import wait_or_stop
from workflow_engine.runtime.leader import LeaderElection
from workflow_engine.services import sweeps
from workflow_engine.services.container import Container

log = get_logger("wfe.scheduler")
STATS_INTERVAL_S = 5
PRUNE_INTERVAL_S = 3600


class Scheduler:
    def __init__(self, container: Container, instance_id: str) -> None:
        self.c = container
        self.election = LeaderElection(
            container.redis, instance_id, container.settings.leader_ttl_s
        )
        self._last_stats = 0.0
        self._last_prune = 0.0

    async def run(self, stopping: asyncio.Event) -> None:
        interval = self.c.settings.scheduler_tick_ms / 1000
        try:
            while not stopping.is_set():
                started = time.monotonic()
                await self.tick()
                remaining = interval - (time.monotonic() - started)
                if remaining > 0:
                    await wait_or_stop(stopping, remaining)
        finally:
            await self.election.release()
            metrics.SCHEDULER_LEADER.set(0)

    async def tick(self) -> bool:
        leader = await self.election.ensure()
        metrics.SCHEDULER_LEADER.set(1 if leader else 0)
        if not leader:
            return False
        now = datetime.now(UTC)
        duties: list[tuple[str, Callable[[], Awaitable[object]]]] = [
            ("schedules", lambda: sweeps.fire_schedules(self.c, now)),
            ("wake", lambda: sweeps.wake_due(self.c, now)),
            ("reap", lambda: sweeps.reap_stale(self.c, now)),
            ("deadlines", lambda: sweeps.enforce_deadlines(self.c, now)),
            ("admission", lambda: sweeps.admit_queued(self.c)),
        ]
        monotonic = time.monotonic()
        if monotonic - self._last_stats >= STATS_INTERVAL_S:
            self._last_stats = monotonic
            duties.append(("stats", lambda: sweeps.queue_stats(self.c, now)))
        if monotonic - self._last_prune >= PRUNE_INTERVAL_S:
            self._last_prune = monotonic
            duties.append(("prune", lambda: sweeps.prune(self.c, now)))
        for name, duty in duties:
            try:
                await duty()
            except Exception:
                log.exception("scheduler_duty_failed", duty=name)
        return True
