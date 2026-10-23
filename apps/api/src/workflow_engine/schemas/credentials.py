from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from workflow_engine.schemas.common import ApiModel


class CredentialCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    type: str = Field(min_length=1, max_length=32)
    description: str = Field(default="", max_length=500)
    data: dict[str, Any] = Field(description="The fields of the type. Secret fields are encrypted.")


class CredentialUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    data: dict[str, Any] | None = Field(
        default=None, description="New values. Omitted secret fields keep their current value."
    )


class CredentialOut(ApiModel):
    id: uuid.UUID
    name: str
    type: str
    description: str
    public_fields: dict[str, Any]
    secret_fields: list[str] = Field(description="Names of the secret fields that are set.")
    key_provider: str
    version: int
    used_by: list[str] = Field(default_factory=list, description="Workflows that reference it.")
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None


class CredentialTypeOut(ApiModel):
    type: str
    name: str
    description: str
    icon: str
    secret_fields: list[str]
    json_schema: dict[str, Any]
