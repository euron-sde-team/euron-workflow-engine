"""The migrations and the models describe the same schema."""

from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import workflow_engine.models  # noqa: F401  (registers every table)
from workflow_engine.db.base import Base


async def test_models_match_the_migrated_schema(database: str) -> None:
    engine = create_async_engine(database)
    async with engine.connect() as conn:

        def diff(sync_conn):  # type: ignore[no-untyped-def]
            context = MigrationContext.configure(sync_conn, opts={"compare_type": True})
            return compare_metadata(context, Base.metadata)

        differences = await conn.run_sync(diff)
        version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    await engine.dispose()
    assert differences == []
    assert version == "0001"
