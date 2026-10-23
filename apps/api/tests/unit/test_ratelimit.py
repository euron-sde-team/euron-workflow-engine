import fakeredis

from workflow_engine.core.ratelimit import RateLimiter


async def test_fixed_window_allows_then_blocks() -> None:
    limiter = RateLimiter(fakeredis.FakeAsyncRedis())
    results = [await limiter.hit("hooks:trigger:1", limit=3) for _ in range(4)]
    assert [r.allowed for r in results] == [True, True, True, False]
    assert results[0].remaining == 2
    assert results[-1].remaining == 0
    assert results[-1].headers()["x-ratelimit-limit"] == "3"


async def test_limits_are_per_key() -> None:
    limiter = RateLimiter(fakeredis.FakeAsyncRedis())
    await limiter.hit("a", limit=1)
    assert (await limiter.hit("b", limit=1)).allowed
