from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from workflow_engine.schemas.common import ApiModel


class ApiKeyCreate(ApiModel):
    name: str = Field(min_length=1, max_length=80)
    role: Literal["viewer", "editor"] = "viewer"
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


class ApiKeyOut(ApiModel):
    id: uuid.UUID
    name: str
    prefix: str
    role: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreated(ApiKeyOut):
    key: str = Field(description="The full key. Shown once; only a keyed hash is stored.")
