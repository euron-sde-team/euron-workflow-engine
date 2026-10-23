"""Async engine and session factory.

JSON columns are encoded with orjson (faster than the standard library and it handles
datetimes and UUIDs natively). Every connection gets a statement timeout and an idle-in-
transaction timeout, so a stuck query or a forgotten transaction cannot hold queue rows
locked for long.
"""

from __future__ import annotations

from typing import Any

import orjson
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from workflow_engine.core.config import Settings


def json_dumps(value: Any) -> str:
    return orjson.dumps(value, option=orjson.OPT_NON_STR_KEYS).decode()


class Database:
    def __init__(self, settings: Settings, *, application_name: str = "workflow-engine") -> None:
        self.engine: AsyncEngine = create_async_engine(
            settings.database_url,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_pre_ping=True,
            pool_recycle=1800,
            echo=settings.database_echo,
            json_serializer=json_dumps,
            json_deserializer=orjson.loads,
            connect_args={
                "server_settings": {
                    "application_name": application_name,
                    # JIT compilation costs more than it saves on short OLTP queries.
                    "jit": "off",
                    "statement_timeout": "30000",
                    "idle_in_transaction_session_timeout": "60000",
                },
            },
        )
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False, autoflush=False)

    def session(self) -> AsyncSession:
        return self.sessionmaker()

    async def ping(self) -> None:
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        await self.engine.dispose()
