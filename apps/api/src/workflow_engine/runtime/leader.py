"""Leader election on one Redis key.

    acquire   SET wfe:scheduler:leader <id> NX PX <ttl>
    renew     if GET == <id> then PEXPIRE        (one atomic script)
    release   if GET == <id> then DEL            (one atomic script)

The lock only avoids duplicate work. Correctness never depends on it: two leaders during a
handover still fire each schedule tick once, because firing is a compare-and-set on the
trigger row plus a per-tick idempotency key.
"""

from __future__ import annotations

from redis.asyncio import Redis
from redis.exceptions import RedisError

from workflow_engine.core.logging import get_logger

LEADER_KEY = "wfe:scheduler:leader"
log = get_logger("wfe.leader")

_RENEW = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('pexpire', KEYS[1], ARGV[2])
end
return 0
"""
_RELEASE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


class LeaderElection:
    def __init__(self, redis: Redis, instance_id: str, ttl_s: int, key: str = LEADER_KEY) -> None:
        self._redis = redis
        self._id = instance_id.encode()
        self._ttl_ms = ttl_s * 1000
        self._key = key
        self.is_leader = False

    async def ensure(self) -> bool:
        """Acquire or renew; returns whether this instance leads after the call."""
        try:
            if self.is_leader:
                renewed = await self._redis.eval(_RENEW, 1, self._key, self._id, self._ttl_ms)
                if not renewed:
                    log.warning("leadership_lost")
                    self.is_leader = False
            if not self.is_leader:
                acquired = await self._redis.set(self._key, self._id, nx=True, px=self._ttl_ms)
                if acquired:
                    log.info("leadership_acquired")
                    self.is_leader = True
        except RedisError as exc:
            if self.is_leader:
                log.warning("leadership_unknown", error=type(exc).__name__)
            self.is_leader = False
        return self.is_leader

    async def release(self) -> None:
        if not self.is_leader:
            return
        try:
            await self._redis.eval(_RELEASE, 1, self._key, self._id)
        except RedisError:
            log.warning("leadership_release_failed")
        self.is_leader = False

    async def current(self) -> str | None:
        try:
            value = await self._redis.get(self._key)
        except RedisError:
            return None
        return value.decode() if isinstance(value, bytes) else value
