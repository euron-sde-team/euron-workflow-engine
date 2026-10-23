from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class Page[T](ApiModel):
    """Offset pagination, for lists that stay small (workflows, credentials, members)."""

    items: list[T]
    total: int
    limit: int
    offset: int


class CursorPage[T](ApiModel):
    """Keyset pagination for lists that grow without bound (executions, events, audit)."""

    items: list[T]
    next_cursor: str | None = Field(
        default=None, description="Pass as `cursor` to get the next page; null on the last."
    )


class Ok(ApiModel):
    ok: bool = True
