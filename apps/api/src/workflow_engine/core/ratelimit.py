"""Fixed-window rate limits in Redis.

One INCR and one EXPIRE per request in a single round trip. Fixed windows allow a short
burst at a window boundary, an accepted trade for O(1) memory per caller.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from redis.asyncio import Redis


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_s: int

    def headers(self) -> dict[str, str]:
        return {
            "x-ratelimit-limit": str(self.limit),
            "x-ratelimit-remaining": str(self.remaining),
            "x-ratelimit-reset": str(self.reset_s),
        }


class RateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def hit(self, key: str, limit: int, window_s: int = 60) -> RateLimitResult:
        now = time.time()
        bucket = int(now // window_s)
        redis_key = f"rl:{key}:{bucket}"
        async with self._redis.pipeline(transaction=False) as pipe:
            pipe.incr(redis_key)
            pipe.expire(redis_key, window_s + 1, nx=True)
            count, _ = await pipe.execute()
        reset_s = int(window_s - (now % window_s)) or window_s
        return RateLimitResult(
            allowed=int(count) <= limit,
            limit=limit,
            remaining=max(0, limit - int(count)),
            reset_s=reset_s,
        )
