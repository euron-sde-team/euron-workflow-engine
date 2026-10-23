"""The executor loop: claim steps, run them concurrently, heartbeat, honour cancellation.

- Up to `WORKER_CONCURRENCY` steps run at once, each in its own task.
- Idle workers sleep on the Redis `wfe:wake` channel, falling back to polling every
  `WORKER_POLL_INTERVAL_MS` if Redis is unavailable.
- Every `STEP_HEARTBEAT_S` one statement refreshes the heartbeat of every held step. A step
  the statement no longer matches was cancelled, reaped or failed by a deadline: its task
  is cancelled and its result is never written.
- `wfe:cancel` messages cancel the running steps of an execution immediately.
- On shutdown the loop stops claiming, waits up to `SHUTDOWN_GRACE_S` for running steps,
  then hands unfinished ones back to the queue without spending an attempt.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid

from redis.exceptions import RedisError
from sqlalchemy import update

from workflow_engine.core import metrics
from workflow_engine.core.logging import get_logger
from workflow_engine.integrations.signals import CANCEL_CHANNEL, WAKE_CHANNEL
from workflow_engine.models import ExecutionStep
from workflow_engine.models.enums import StepStatus
from workflow_engine.repositories.executions import StepRepository
from workflow_engine.runtime.clock import wait_or_stop
from workflow_engine.services.container import Container
from workflow_engine.services.steps import ClaimedStep, StepRunner

log = get_logger("wfe.executor")


class Executor:
    def __init__(self, container: Container, worker_id: str) -> None:
        self.c = container
        self.worker_id = worker_id
        self.concurrency = container.settings.worker_concurrency
        self.runner = StepRunner(container, worker_id)
        self.inflight: dict[uuid.UUID, tuple[asyncio.Task[None], uuid.UUID]] = {}
        self.wake = asyncio.Event()
        self.lost: set[uuid.UUID] = set()

    @property
    def busy(self) -> int:
        return len(self.inflight)

    async def run(self, stopping: asyncio.Event) -> None:
        listener = asyncio.create_task(self._listen(stopping))
        heartbeat = asyncio.create_task(self._heartbeat(stopping))
        poll = self.c.settings.worker_poll_interval_ms / 1000
        try:
            while not stopping.is_set():
                free = self.concurrency - len(self.inflight)
                claimed: list[ClaimedStep] = []
                if free > 0:
                    try:
                        claimed = await self.runner.claim(free)
                    except Exception:
                        log.exception("claim_failed")
                        await asyncio.sleep(poll)
                        continue
                    for step in claimed:
                        self._spawn(step)
                if claimed and len(claimed) == free:
                    continue  # there may be more ready right away
                await self._idle(stopping, poll)
        finally:
            await self._drain()
            listener.cancel()
            heartbeat.cancel()
            await asyncio.gather(listener, heartbeat, return_exceptions=True)

    def _spawn(self, step: ClaimedStep) -> None:
        task = asyncio.create_task(self._execute(step), name=f"step-{step.id}")
        self.inflight[step.id] = (task, step.execution_id)
        metrics.WORKER_SLOTS_BUSY.set(len(self.inflight))

        def done(_: asyncio.Task[None]) -> None:
            self.inflight.pop(step.id, None)
            self.lost.discard(step.id)
            metrics.WORKER_SLOTS_BUSY.set(len(self.inflight))
            self.wake.set()  # a slot is free

        task.add_done_callback(done)

    async def _execute(self, step: ClaimedStep) -> None:
        try:
            await self.runner.execute(step)
        except asyncio.CancelledError:
            if step.id in self.lost:
                log.info("step_abandoned", step_id=str(step.id), reason="claim_lost")
                return
            raise
        except Exception:
            log.exception("step_crashed", step_id=str(step.id))

    async def _idle(self, stopping: asyncio.Event, poll: float) -> None:
        self.wake.clear()
        waiters = [asyncio.create_task(self.wake.wait()), asyncio.create_task(stopping.wait())]
        try:
            await asyncio.wait(waiters, timeout=poll, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for waiter in waiters:
                waiter.cancel()

    async def _listen(self, stopping: asyncio.Event) -> None:
        while not stopping.is_set():
            pubsub = self.c.redis.pubsub()
            try:
                await pubsub.subscribe(WAKE_CHANNEL, CANCEL_CHANNEL)
                while not stopping.is_set():
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if message is None:
                        continue
                    channel = message.get("channel")
                    channel = channel.decode() if isinstance(channel, bytes) else channel
                    if channel == WAKE_CHANNEL:
                        self.wake.set()
                    elif channel == CANCEL_CHANNEL:
                        self._cancel_execution(message.get("data"))
            except (RedisError, OSError):
                log.warning("signal_listener_disconnected")
                await asyncio.sleep(2)
            finally:
                with contextlib.suppress(Exception):
                    await pubsub.aclose()  # type: ignore[no-untyped-call]

    def _cancel_execution(self, data: object) -> None:
        raw = data.decode() if isinstance(data, bytes) else str(data)
        try:
            execution_id = uuid.UUID(raw)
        except ValueError:
            return
        for step_id, (task, owner) in list(self.inflight.items()):
            if owner == execution_id:
                self.lost.add(step_id)
                task.cancel()

    async def _heartbeat(self, stopping: asyncio.Event) -> None:
        interval = self.c.settings.step_heartbeat_s
        while not stopping.is_set():
            await wait_or_stop(stopping, interval)
            ids = list(self.inflight)
            if not ids:
                continue
            try:
                async with self.c.db.session() as session:
                    held = await StepRepository(session).heartbeat(self.worker_id, ids)
                    await session.commit()
            except Exception:
                # A database blip must not kill healthy steps; the next beat retries.
                log.warning("heartbeat_failed", steps=len(ids))
                continue
            for step_id in set(ids) - held - self.runner.recording:
                entry = self.inflight.get(step_id)
                if entry is not None:
                    log.info("claim_lost", step_id=str(step_id))
                    self.lost.add(step_id)
                    entry[0].cancel()

    async def _drain(self) -> None:
        if not self.inflight:
            return
        tasks = [task for task, _ in self.inflight.values()]
        log.info("draining", steps=len(tasks), grace_s=self.c.settings.shutdown_grace_s)
        _, pending = await asyncio.wait(tasks, timeout=self.c.settings.shutdown_grace_s)
        if not pending:
            return
        unfinished = [step_id for step_id, (task, _) in self.inflight.items() if task in pending]
        for step_id in unfinished:
            self.lost.add(step_id)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await self._release(unfinished)

    async def _release(self, step_ids: list[uuid.UUID]) -> None:
        """Hand interrupted steps back to the queue; the interruption does not cost an attempt."""
        if not step_ids:
            return
        try:
            async with self.c.db.session() as session:
                await session.execute(
                    update(ExecutionStep)
                    .where(
                        ExecutionStep.id.in_(step_ids),
                        ExecutionStep.locked_by == self.worker_id,
                        ExecutionStep.status == StepStatus.RUNNING,
                    )
                    .values(
                        status=StepStatus.QUEUED,
                        locked_by=None,
                        heartbeat_at=None,
                        attempt=ExecutionStep.attempt - 1,
                    )
                    .execution_options(synchronize_session=False)
                )
                await session.commit()
            log.info("released", steps=len(step_ids))
        except Exception:
            log.exception("release_failed")
