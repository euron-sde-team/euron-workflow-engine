from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from workflow_engine.schemas.common import ApiModel

EVENT_NAME = r"^[a-z0-9][a-z0-9_.-]{0,118}[a-z0-9]$"


class EventPublish(ApiModel):
    name: str = Field(pattern=EVENT_NAME, description="For example order.created")
    payload: Any = Field(default_factory=dict)


class EventPublished(ApiModel):
    event_id: uuid.UUID
    matched: int
    executions: list[uuid.UUID]


class EventOut(ApiModel):
    id: uuid.UUID
    name: str
    payload: Any = None
    source: str
    source_execution_id: uuid.UUID | None
    depth: int
    matched: int
    created_at: datetime
