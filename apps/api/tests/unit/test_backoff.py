import random

from workflow_engine.engine.backoff import retry_delay_ms, schedule
from workflow_engine.engine.definition import RetryPolicy


def test_exponential_growth_without_jitter_is_exact_and_capped() -> None:
    policy = RetryPolicy(max_attempts=6, initial_delay_ms=1000, max_delay_ms=5000, jitter=False)
    assert [retry_delay_ms(policy, attempt) for attempt in range(1, 6)] == [
        1000,
        2000,
        4000,
        5000,
        5000,
    ]


def test_equal_jitter_stays_between_half_and_the_full_delay() -> None:
    policy = RetryPolicy(max_attempts=5, initial_delay_ms=1000, max_delay_ms=60_000, multiplier=3)
    rng = random.Random(7)
    for attempt in range(1, 5):
        full = 1000 * 3 ** (attempt - 1)
        for _ in range(50):
            delay = retry_delay_ms(policy, attempt, rng)
            assert full // 2 <= delay <= full


def test_jitter_spreads_retries() -> None:
    policy = RetryPolicy(max_attempts=3, initial_delay_ms=10_000)
    rng = random.Random(1)
    delays = {retry_delay_ms(policy, 2, rng) for _ in range(20)}
    assert len(delays) > 10


def test_schedule_preview() -> None:
    policy = RetryPolicy(max_attempts=4, initial_delay_ms=500, max_delay_ms=1500)
    assert schedule(policy) == [(250, 500), (500, 1000), (750, 1500)]
    assert schedule(RetryPolicy(max_attempts=1)) == []
