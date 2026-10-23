"""Workers announce themselves in Redis so the dashboard can list them."""

from __future__ import annotations

import os
import socket
from datetime import UTC, datetime
from typing import Any

import orjson
from redis.asyncio import Redis
from redis.exceptions import RedisError

from workflow_engine import __version__

PREFIX = "wfe:workers:"
TTL_S = 30


async def announce(redis: Redis, worker_id: str, **status: Any) -> None:
    body = {
        "id": worker_id,
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "version": __version__,
        "seen_at": datetime.now(UTC).isoformat(),
        **status,
    }
    try:
        await redis.set(f"{PREFIX}{worker_id}", orjson.dumps(body), ex=TTL_S)
    except RedisError:
        return


async def withdraw(redis: Redis, worker_id: str) -> None:
    try:
        await redis.delete(f"{PREFIX}{worker_id}")
    except RedisError:
        return


async def live_workers(redis: Redis) -> list[dict[str, Any]]:
    workers: list[dict[str, Any]] = []
    try:
        keys = [key async for key in redis.scan_iter(match=f"{PREFIX}*", count=100)]
        if keys:
            workers.extend(orjson.loads(raw) for raw in await redis.mget(keys) if raw)
    except RedisError:
        return []
    return sorted(workers, key=lambda w: str(w.get("id")))
