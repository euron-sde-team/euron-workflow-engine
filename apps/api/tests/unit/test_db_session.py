"""The database password on AWS comes from the RDS-managed secret, cached briefly."""

from __future__ import annotations

from typing import Any

import orjson
import pytest
from sqlalchemy import event

from workflow_engine.core.config import Settings
from workflow_engine.db import session as db_session
from workflow_engine.db.session import SecretPassword, create_engine


class FakeSecrets:
    def __init__(self) -> None:
        self.calls = 0
        self.password = "first"

    def get_secret_value(self, SecretId: str) -> dict[str, Any]:  # noqa: N803 (boto3 casing)
        self.calls += 1
        assert SecretId == "arn:secret"
        return {"SecretString": orjson.dumps({"username": "wfe", "password": self.password})}


def test_the_password_is_fetched_once_per_ttl() -> None:
    client = FakeSecrets()
    password = SecretPassword(client, "arn:secret", ttl_s=60)
    assert password.current() == "first"
    client.password = "rotated"
    assert password.current() == "first"
    assert client.calls == 1


def test_a_rotated_password_is_picked_up_after_the_ttl() -> None:
    client = FakeSecrets()
    password = SecretPassword(client, "arn:secret", ttl_s=0)
    assert password.current() == "first"
    client.password = "rotated"
    assert password.current() == "rotated"
    params: dict[str, Any] = {}
    password.inject(None, None, None, params)
    assert params == {"password": "rotated"}


def test_engines_inject_the_secret_only_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[SecretPassword] = []

    class Recording(SecretPassword):
        def __init__(self, client: Any, arn: str, ttl_s: float = 60) -> None:
            super().__init__(client, arn, ttl_s)
            created.append(self)

    monkeypatch.setattr(db_session, "SecretPassword", Recording)
    plain = create_engine(Settings(), pooled=False)
    assert not created
    secret = create_engine(
        Settings(database_secret_arn="arn:aws:secretsmanager:us-east-1:1:secret:db"), pooled=False
    )
    assert len(created) == 1
    assert event.contains(secret.sync_engine, "do_connect", created[0].inject)
    assert not event.contains(plain.sync_engine, "do_connect", created[0].inject)
