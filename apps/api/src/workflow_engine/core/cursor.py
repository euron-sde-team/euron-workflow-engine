"""Opaque keyset-pagination cursors.

A cursor carries the sort key of the last row returned (`created_at` and `id`), so the next
page is `WHERE (created_at, id) < (cursor)`: an index range scan, stable while new rows
arrive, and as fast on page 1000 as on page 1. Clients treat it as an opaque string.
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime

import orjson

from workflow_engine.core.errors import UnprocessableError


def encode(created_at: datetime, row_id: uuid.UUID | int) -> str:
    raw = orjson.dumps([created_at.isoformat(), str(row_id)])
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        moment, row_id = orjson.loads(base64.urlsafe_b64decode(padded.encode()))
        return datetime.fromisoformat(moment), str(row_id)
    except (ValueError, TypeError, orjson.JSONDecodeError) as exc:
        raise UnprocessableError("That page cursor is not valid.", code="invalid_cursor") from exc


def decode_uuid(cursor: str) -> tuple[datetime, uuid.UUID]:
    moment, row_id = decode(cursor)
    try:
        return moment, uuid.UUID(row_id)
    except ValueError as exc:
        raise UnprocessableError("That page cursor is not valid.", code="invalid_cursor") from exc
