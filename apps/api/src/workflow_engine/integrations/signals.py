"""Redis pub/sub signals between processes: new work is ready, an execution was cancelled.

Signals only cut latency. Losing one is harmless: workers poll on an interval anyway and
heartbeats notice cancellation, so every publish is best effort and never raises.
"""

from __future__ import annotations

import uuid

from redis.asyncio import Redis
from redis.exceptions import RedisError

from workflow_engine.core.logging import get_logger

WAKE_CHANNEL = "wfe:wake"
CANCEL_CHANNEL = "wfe:cancel"
log = get_logger("wfe.signals")


class Signals:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def wake(self) -> None:
        try:
            await self._redis.publish(WAKE_CHANNEL, b"1")
        except RedisError as exc:
            log.warning("signal_failed", channel=WAKE_CHANNEL, error=type(exc).__name__)

    async def cancel(self, execution_id: uuid.UUID) -> None:
        try:
            await self._redis.publish(CANCEL_CHANNEL, str(execution_id).encode())
        except RedisError as exc:
            log.warning("signal_failed", channel=CANCEL_CHANNEL, error=type(exc).__name__)
