"""Time-ordered UUIDs (RFC 9562 version 7).

Random v4 keys scatter inserts across the whole primary-key index; v7 keys arrive in
roughly increasing order, so hot B-tree pages stay in cache as tables grow.
"""

from __future__ import annotations

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    unix_ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    value = (
        (unix_ms & 0xFFFF_FFFF_FFFF) << 80
        | 0x7 << 76
        | ((rand >> 64) & 0xFFF) << 64
        | 0b10 << 62
        | (rand & 0x3FFF_FFFF_FFFF_FFFF)
    )
    return uuid.UUID(int=value)
