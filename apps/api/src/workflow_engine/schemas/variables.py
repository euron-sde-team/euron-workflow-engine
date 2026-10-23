from __future__ import annotations

from datetime import datetime

from pydantic import Field

from workflow_engine.schemas.common import ApiModel

VARIABLE_KEY = r"^[A-Z][A-Z0-9_]{0,63}$"


class VariableIn(ApiModel):
    value: str = Field(max_length=10_000)
    description: str = Field(default="", max_length=500)


class VariableOut(ApiModel):
    key: str
    value: str
    description: str
    updated_at: datetime
