"""The worker process: step executor plus scheduler candidate.

    python -m workflow_engine.worker      (or: wfe worker)

Run as many as you like. Each claims steps from Postgres; one of them at a time (elected
through Redis) also runs the scheduler. SIGTERM stops claiming, lets running steps finish
for SHUTDOWN_GRACE_S, hands the rest back to the queue and releases leadership.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import signal
import socket

from prometheus_client import start_http_server

from workflow_engine.core.config import Settings, get_settings
from workflow_engine.core.logging import configure_logging, get_logger
from workflow_engine.db.migrate import migrate
from workflow_engine.runtime import presence
from workflow_engine.runtime.clock import wait_or_stop
from workflow_engine.runtime.executor import Executor
from workflow_engine.runtime.scheduler import Scheduler
from workflow_engine.services.container import Container, build_container

log = get_logger("wfe.worker")
PRESENCE_INTERVAL_S = 10


def worker_id() -> str:
    return f"{socket.gethostname()[:40]}-{os.getpid()}-{secrets.token_hex(2)}"


async def _announce(
    container: Container,
    wid: str,
    executor: Executor,
    scheduler: Scheduler | None,
    stopping: asyncio.Event,
) -> None:
    while not stopping.is_set():
        await presence.announce(
            container.redis,
            wid,
            concurrency=executor.concurrency,
            busy=executor.busy,
            leader=bool(scheduler and scheduler.election.is_leader),
        )
        await wait_or_stop(stopping, PRESENCE_INTERVAL_S)
    await presence.withdraw(container.redis, wid)


async def run(settings: Settings, *, scheduler_enabled: bool | None = None) -> None:
    if settings.migrate_on_boot:
        await migrate(settings)
    container = build_container(settings, application_name="wfe-worker")
    wid = worker_id()
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopping.set)
    executor = Executor(container, wid)
    enabled = settings.scheduler_enabled if scheduler_enabled is None else scheduler_enabled
    scheduler = Scheduler(container, wid) if enabled else None
    log.info("worker_started", worker=wid, concurrency=executor.concurrency, scheduler=enabled)
    tasks = [
        asyncio.create_task(executor.run(stopping)),
        asyncio.create_task(_announce(container, wid, executor, scheduler, stopping)),
    ]
    if scheduler is not None:
        tasks.append(asyncio.create_task(scheduler.run(stopping)))
    try:
        await asyncio.gather(*tasks)
    finally:
        await container.close()
        log.info("worker_stopped", worker=wid)


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    if settings.is_production and (problems := settings.production_problems()):
        raise SystemExit("Refusing to start in production:\n  - " + "\n  - ".join(problems))
    if settings.worker_metrics_port:
        start_http_server(settings.worker_metrics_port)
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
