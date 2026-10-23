"""Apply pending migrations from inside the application.

Runs under a transaction-scoped advisory lock, so any number of API replicas can boot at
the same time and the migrations still run exactly once.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import workflow_engine

# Arbitrary, stable 64-bit key: "wfengine" in ASCII.
MIGRATION_LOCK_KEY = 0x7766656E67696E65


def alembic_config() -> Config:
    config = Config()
    config.set_main_option(
        "script_location", str(Path(workflow_engine.__file__).parent / "migrations")
    )
    return config


def _upgrade(connection: Connection, revision: str) -> None:
    config = alembic_config()
    config.attributes["connection"] = connection
    command.upgrade(config, revision)


async def migrate(database_url: str, revision: str = "head") -> None:
    engine = create_async_engine(database_url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK_KEY}
            )
            await conn.run_sync(_upgrade, revision)
    finally:
        await engine.dispose()
