"""`make demo` end to end, in its own database: real runs, then two weeks of spread history."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import boto3
import pytest
from botocore.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.conftest import AWS_URL, SERVER_URL
from workflow_engine.core.config import Settings
from workflow_engine.db.migrate import migrate
from workflow_engine.demo import seed
from workflow_engine.models import DeadLetter, Execution, User, Workflow
from workflow_engine.services.container import build_container

DATABASE = "wfe_seed_it"


@pytest.fixture
async def seed_settings(settings: Settings, demo_apis: str) -> Settings:
    admin = create_async_engine(SERVER_URL, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f"DROP DATABASE IF EXISTS {DATABASE} WITH (FORCE)"))
        await conn.execute(text("DROP DATABASE IF EXISTS warehouse WITH (FORCE)"))
        await conn.execute(text(f"CREATE DATABASE {DATABASE}"))
    await admin.dispose()
    sqs = boto3.client("sqs", endpoint_url=AWS_URL, config=Config(region_name="us-east-1"))
    sqs.create_queue(QueueName="order-events")
    configured = settings.model_copy(
        update={
            "database_url": SERVER_URL.rsplit("/", 1)[0] + f"/{DATABASE}",
            "sqs_allowed_queues": ["order-events"],
            "demo_apis_url": demo_apis,
            "redis_url": settings.redis_url.rsplit("/", 1)[0] + "/3",
        }
    )
    await migrate(configured.database_url)
    return configured


async def test_the_demo_seed_builds_a_realistic_workspace(seed_settings: Settings) -> None:
    await seed.run(seed_settings, "demo-password-for-tests", history_days=14)
    container = build_container(seed_settings)
    try:
        async with container.db.session() as session:
            people = (
                (await session.execute(select(User.email).order_by(User.email))).scalars().all()
            )
            assert people == [
                "lena@northwind.example.com",
                "maya@northwind.example.com",
                "ravi@northwind.example.com",
            ]
            workflows = (await session.execute(select(Workflow.name, Workflow.active))).all()
            assert len(workflows) == 8
            assert sum(1 for _, active in workflows if active) == 7
            statuses = dict(
                (
                    await session.execute(
                        select(Execution.status, func.count()).group_by(Execution.status)
                    )
                ).all()
            )
            assert statuses.get("succeeded", 0) > 100
            assert statuses.get("failed", 0) >= 3
            assert statuses.get("waiting", 0) == 4
            assert statuses.get("cancelled", 0) == 1
            assert statuses.get("queued", 0) == 0
            assert statuses.get("running", 0) == 0
            oldest = await session.scalar(select(func.min(Execution.created_at)))
            assert oldest is not None
            assert oldest < datetime.now(UTC) - timedelta(days=7)
            letters = dict(
                (
                    await session.execute(
                        select(DeadLetter.status, func.count()).group_by(DeadLetter.status)
                    )
                ).all()
            )
            assert letters.get("open", 0) >= 2
            assert letters.get("discarded", 0) == 1
        # Running it again is harmless.
        await seed.run(seed_settings, "demo-password-for-tests")
    finally:
        await container.close()
