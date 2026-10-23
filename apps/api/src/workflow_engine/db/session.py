"""Async engine and session factory.

JSON columns are encoded with orjson (faster than the standard library and it handles
datetimes and UUIDs natively). Every connection gets a statement timeout and an idle-in-
transaction timeout, so a stuck query or a forgotten transaction cannot hold queue rows
locked for long.

With DATABASE_SECRET_ARN set (AWS), each new connection reads the password from the
RDS-managed secret, cached for a minute, so a password rotation needs no redeploy.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import orjson
from sqlalchemy import event, pool, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from workflow_engine.core.config import Settings
from workflow_engine.integrations.aws import AwsClients

PASSWORD_TTL_S = 60


def json_dumps(value: Any) -> str:
    return orjson.dumps(value, option=orjson.OPT_NON_STR_KEYS).decode()


class SecretPassword:
    """The current database password from Secrets Manager, refreshed at most once a minute."""

    def __init__(self, client: Any, secret_arn: str, ttl_s: float = PASSWORD_TTL_S) -> None:
        self._client = client
        self._arn = secret_arn
        self._ttl_s = ttl_s
        self._value: str | None = None
        self._fetched = 0.0
        self._lock = threading.Lock()

    def current(self) -> str:
        with self._lock:
            if self._value is None or time.monotonic() - self._fetched > self._ttl_s:
                secret = self._client.get_secret_value(SecretId=self._arn)
                self._value = str(orjson.loads(secret["SecretString"])["password"])
                self._fetched = time.monotonic()
            return self._value

    def inject(self, _dialect: Any, _record: Any, _cargs: Any, cparams: dict[str, Any]) -> None:
        cparams["password"] = self.current()


def create_engine(
    settings: Settings, *, application_name: str = "workflow-engine", pooled: bool = True
) -> AsyncEngine:
    options: dict[str, Any] = {
        "pool_pre_ping": True,
        "echo": settings.database_echo,
        "json_serializer": json_dumps,
        "json_deserializer": orjson.loads,
        "connect_args": {
            "server_settings": {
                "application_name": application_name,
                # JIT compilation costs more than it saves on short OLTP queries.
                "jit": "off",
                "statement_timeout": "30000",
                "idle_in_transaction_session_timeout": "60000",
            },
        },
    }
    if pooled:
        options |= {
            "pool_size": settings.database_pool_size,
            "max_overflow": settings.database_max_overflow,
            "pool_recycle": 1800,
        }
    else:
        options["poolclass"] = pool.NullPool
    engine = create_async_engine(settings.database_url, **options)
    if settings.database_secret_arn:
        password = SecretPassword(AwsClients(settings).secrets(), settings.database_secret_arn)
        event.listen(engine.sync_engine, "do_connect", password.inject)
    return engine


class Database:
    def __init__(self, settings: Settings, *, application_name: str = "workflow-engine") -> None:
        self.engine: AsyncEngine = create_engine(settings, application_name=application_name)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False, autoflush=False)

    def session(self) -> AsyncSession:
        return self.sessionmaker()

    async def ping(self) -> None:
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        await self.engine.dispose()
