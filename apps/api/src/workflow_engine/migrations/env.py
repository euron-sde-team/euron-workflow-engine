"""Alembic environment.

Two entry points share it: the `alembic` CLI (opens its own async engine from
DATABASE_URL) and `workflow_engine.db.migrate`, which passes in a connection that already holds
the migration advisory lock.
"""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import workflow_engine.models  # noqa: F401  (registers every table on the metadata)
from workflow_engine.core.config import get_settings
from workflow_engine.db.base import Base

config = context.config
target_metadata = Base.metadata


def _configure(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def _run_with_new_engine() -> None:
    engine = create_async_engine(get_settings().database_url, poolclass=pool.NullPool)
    async with engine.begin() as connection:
        await connection.run_sync(_configure)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
elif (shared := config.attributes.get("connection")) is not None:
    _configure(shared)
else:
    asyncio.run(_run_with_new_engine())
