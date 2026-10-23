"""Credential types: what each holds, which fields are secret, how each is validated.

Secret fields are encrypted and never returned. Non-secret fields (a username, a host) are
stored in the clear so people can recognise a credential without seeing its secret.
"""

from __future__ import annotations

import builtins
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def secret(**kwargs: Any) -> Any:
    return Field(..., json_schema_extra={"x-secret": True}, **kwargs)


class _Fields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class HttpBearer(_Fields):
    token: str = secret(min_length=1, max_length=8000)


class HttpBasic(_Fields):
    username: str = Field(min_length=1, max_length=200)
    password: str = secret(min_length=1, max_length=1000)


class HttpHeader(_Fields):
    header_name: str = Field(pattern=r"^[A-Za-z0-9-]{1,100}$")
    header_value: str = secret(min_length=1, max_length=8000)


class HttpQuery(_Fields):
    param_name: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,100}$")
    param_value: str = secret(min_length=1, max_length=4000)


class WebhookSecret(_Fields):
    secret: str = secret(min_length=16, max_length=500)


class Postgres(_Fields):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=63)
    user: str = Field(min_length=1, max_length=63)
    password: str = secret(min_length=1, max_length=1000)
    ssl_mode: Literal["disable", "prefer", "require", "verify-full"] = "prefer"


class SlackWebhook(_Fields):
    url: str = secret(min_length=10, max_length=1000)

    @field_validator("url")
    @classmethod
    def _http_url(cls, value: str) -> str:
        if not value.startswith(("https://", "http://")):
            raise ValueError("Paste the full webhook URL, starting with https://")
        return value


@dataclass(frozen=True)
class CredentialType:
    type: str
    name: str
    description: str
    icon: str
    model: builtins.type[BaseModel]

    @property
    def secret_fields(self) -> frozenset[str]:
        return frozenset(
            name
            for name, info in self.model.model_fields.items()
            if isinstance(info.json_schema_extra, dict) and info.json_schema_extra.get("x-secret")
        )

    def split(self, values: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """(public fields, secret fields) of validated values."""
        public = {k: v for k, v in values.items() if k not in self.secret_fields}
        hidden = {k: v for k, v in values.items() if k in self.secret_fields}
        return public, hidden


CREDENTIAL_TYPES: dict[str, CredentialType] = {
    t.type: t
    for t in (
        CredentialType(
            "http_bearer",
            "Bearer token",
            "Sent as Authorization: Bearer <token>.",
            "key-round",
            HttpBearer,
        ),
        CredentialType(
            "http_basic",
            "Basic auth",
            "A username and password for HTTP basic authentication.",
            "user-round-key",
            HttpBasic,
        ),
        CredentialType(
            "http_header",
            "API key header",
            "A secret sent in a header of your choice.",
            "file-key",
            HttpHeader,
        ),
        CredentialType(
            "http_query",
            "API key query parameter",
            "A secret sent as a query parameter.",
            "link",
            HttpQuery,
        ),
        CredentialType(
            "webhook_secret",
            "Webhook secret",
            "Verifies signed or token-protected incoming webhooks.",
            "shield-check",
            WebhookSecret,
        ),
        CredentialType(
            "postgres",
            "Postgres connection",
            "Host, database and login for the Postgres node.",
            "database",
            Postgres,
        ),
        CredentialType(
            "slack_webhook",
            "Slack webhook",
            "An incoming-webhook URL for the Slack node.",
            "message-square",
            SlackWebhook,
        ),
    )
}
