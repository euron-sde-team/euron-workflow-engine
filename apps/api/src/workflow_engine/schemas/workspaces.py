from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import EmailStr, Field, field_validator

from workflow_engine.schemas.common import ApiModel


class WorkspaceSettings(ApiModel):
    """Per-workspace defaults."""

    timezone: str = Field(
        default="UTC", description="Default time zone for new schedules and for the dashboard."
    )
    retention_days: int = Field(
        default=30, ge=1, le=3650, description="Finished executions older than this are deleted."
    )
    default_timeout_s: int = Field(
        default=3600, ge=10, le=604_800, description="Execution timeout for new workflows."
    )

    @field_validator("timezone")
    @classmethod
    def _known_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown time zone '{value}'") from exc
        return value


class WorkspaceCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)


class WorkspaceUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    settings: WorkspaceSettings | None = None


class WorkspaceOut(ApiModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str
    settings: WorkspaceSettings
    role: str
    created_at: datetime


class MemberOut(ApiModel):
    user_id: uuid.UUID
    email: str
    name: str
    role: str
    joined_at: datetime


class MemberAdd(ApiModel):
    email: EmailStr
    name: str | None = Field(default=None, max_length=120)
    role: Literal["owner", "editor", "viewer"] = "viewer"


class MemberAdded(ApiModel):
    member: MemberOut
    temporary_password: str | None = Field(
        default=None, description="Set only when the account was created by this call. Shown once."
    )


class MemberUpdate(ApiModel):
    role: Literal["owner", "editor", "viewer"]
