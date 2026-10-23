"""Sleeping that wakes up early when the process is asked to stop."""

from __future__ import annotations

import asyncio
import contextlib


async def wait_or_stop(stopping: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stopping.wait(), timeout=seconds)
