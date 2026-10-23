"""Retry delays: exponential backoff, capped, with equal jitter.

    delay(attempt) = min(max_delay, initial * multiplier ** (attempt - 1))
    jittered       = delay / 2 + uniform(0, delay / 2)

Equal jitter keeps a floor of half the delay (a struggling service always gets some rest)
while spreading retries from many executions so they do not arrive in lockstep.
"""

from __future__ import annotations

import random

from workflow_engine.engine.definition import RetryPolicy


def retry_delay_ms(policy: RetryPolicy, attempt: int, rng: random.Random | None = None) -> int:
    """Delay before the next attempt, after attempt number `attempt` (1-based) failed."""
    exponent = max(0, attempt - 1)
    delay = min(float(policy.max_delay_ms), policy.initial_delay_ms * policy.multiplier**exponent)
    if not policy.jitter:
        return int(delay)
    half = delay / 2
    return int(half + (rng or random).uniform(0, half))


def schedule(policy: RetryPolicy) -> list[tuple[int, int]]:
    """The (min, max) delay in milliseconds before each retry, for the editor's preview."""
    windows = []
    for attempt in range(1, policy.max_attempts):
        delay = int(
            min(policy.max_delay_ms, policy.initial_delay_ms * policy.multiplier ** (attempt - 1))
        )
        windows.append((delay // 2, delay) if policy.jitter else (delay, delay))
    return windows
