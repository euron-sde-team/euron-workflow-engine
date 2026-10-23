"""Integration fixtures: a fresh database, Redis, the Floci emulator and Mailpit.

Start the services with `scripts/test-deps.sh up` (or `make test-integration`, which does).
The suite creates its own database (`wfe_it`), migrates it, provisions a KMS key, a bucket,
queues and an SES identity in the emulator, and runs the real app in process.
"""

from __future__ import annotations

import contextlib
import os
import socket
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import boto3
import httpx
import pytest
from botocore.config import Config
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from workflow_engine.core.config import Settings
from workflow_engine.db.migrate import migrate
from workflow_engine.main import create_app
from workflow_engine.services.container import Container

SERVER_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://wfe:wfe@127.0.0.1:9135/wfe")
REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:9136/0")
AWS_URL = os.environ.get("TEST_AWS_ENDPOINT_URL", "http://127.0.0.1:9137")
MAILPIT_URL = os.environ.get("TEST_MAILPIT_URL", "http://127.0.0.1:9138")
DATABASE = "wfe_it"
DATABASE_URL = SERVER_URL.rsplit("/", 1)[0] + f"/{DATABASE}"
PASSWORD = "correct-horse-battery-staple"
RUN = uuid.uuid4().hex[:8]
BUCKET = f"wfe-it-data-{RUN}"
QUEUE = f"wfe-it-events-{RUN}"
FIFO_QUEUE = f"wfe-it-orders-{RUN}.fifo"
MAIL_FROM = "Euron WorkflowEngine <automations@wfe.example.test>"

os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")


def _reachable(url: str, default_port: int) -> bool:
    parts = urlsplit(url.replace("postgresql+asyncpg", "postgresql"))
    try:
        with socket.create_connection(
            (parts.hostname or "127.0.0.1", parts.port or default_port), 2
        ):
            return True
    except OSError:
        return False


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def aws_resources() -> dict[str, str]:
    config = Config(region_name="us-east-1", s3={"addressing_style": "path"})
    kms = boto3.client("kms", endpoint_url=AWS_URL, config=config)
    key_id = kms.create_key(Description=f"wfe integration {RUN}")["KeyMetadata"]["KeyId"]
    alias = f"alias/wfe-it-{RUN}"
    kms.create_alias(AliasName=alias, TargetKeyId=key_id)
    boto3.client("s3", endpoint_url=AWS_URL, config=config).create_bucket(Bucket=BUCKET)
    sqs = boto3.client("sqs", endpoint_url=AWS_URL, config=config)
    queue_url = sqs.create_queue(QueueName=QUEUE)["QueueUrl"]
    sqs.create_queue(
        QueueName=FIFO_QUEUE,
        Attributes={"FifoQueue": "true", "ContentBasedDeduplication": "true"},
    )
    ses = boto3.client("sesv2", endpoint_url=AWS_URL, config=config)
    with contextlib.suppress(ses.exceptions.AlreadyExistsException):
        ses.create_email_identity(EmailIdentity="automations@wfe.example.test")
    return {"kms_alias": alias, "bucket": BUCKET, "queue": QUEUE, "queue_url": queue_url}


@pytest.fixture(scope="session")
def settings(aws_resources: dict[str, str]) -> Settings:
    for url, port, name in (
        (SERVER_URL, 5432, "Postgres"),
        (REDIS_URL, 6379, "Redis"),
        (AWS_URL, 4566, "Floci"),
    ):
        if not _reachable(url, port):
            pytest.exit(f"{name} is not reachable at {url}: run scripts/test-deps.sh up", 2)
    return Settings(
        app_env="test",
        log_level="warning",
        log_format="console",
        database_url=DATABASE_URL,
        database_pool_size=10,
        redis_url=REDIS_URL,
        session_secret="integration-session-secret-0123456789",
        api_key_pepper="integration-api-key-pepper-0123456789",
        aws_endpoint_url=AWS_URL,
        vault_provider="kms",
        kms_key_id=aws_resources["kms_alias"],
        mail_from=MAIL_FROM,
        workflow_data_bucket=BUCKET,
        sqs_allowed_queues=[QUEUE, FIFO_QUEUE],
        outbound_allow_private_networks=True,
        allow_signup=True,
        worker_poll_interval_ms=100,
        scheduler_tick_ms=200,
        step_heartbeat_s=1,
        step_stale_s=5,
        rate_limit_login=1000,
        rate_limit_webhook=1000,
        rate_limit_test_run=1000,
        rate_limit_events=1000,
    )


@pytest.fixture(scope="session")
async def database(settings: Settings) -> str:
    admin = create_async_engine(SERVER_URL, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f"DROP DATABASE IF EXISTS {DATABASE} WITH (FORCE)"))
        await conn.execute(text(f"CREATE DATABASE {DATABASE}"))
    await admin.dispose()
    await migrate(settings.database_url)
    redis = Redis.from_url(settings.redis_url)
    await redis.flushdb()
    await redis.aclose()
    return settings.database_url


@pytest.fixture(scope="session")
async def app(settings: Settings, database: str) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture(scope="session")
def container(app: FastAPI) -> Container:
    built: Container = app.state.container
    return built


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"origin": "http://localhost:3130"},
    ) as c:
        yield c


@dataclass
class Account:
    email: str
    token: str
    user_id: str
    workspace: str

    @property
    def headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self.token}"}


async def signup(client: httpx.AsyncClient, name: str = "Maya Patel") -> Account:
    email = f"{name.split()[0].lower()}-{uuid.uuid4().hex[:8]}@northwind.example.com"
    response = await client.post(
        "/api/v1/auth/signup", json={"email": email, "name": name, "password": PASSWORD}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    client.cookies.clear()
    headers = {"authorization": f"Bearer {body['token']}"}
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    return Account(email, body["token"], body["user"]["id"], me["workspaces"][0]["slug"])


@pytest.fixture
async def owner(client: httpx.AsyncClient) -> Account:
    return await signup(client)


@pytest.fixture
async def stranger(client: httpx.AsyncClient) -> Account:
    return await signup(client, "Theo Stranger")


def mailpit_messages() -> list[dict[str, Any]]:
    response = httpx.get(f"{MAILPIT_URL}/api/v1/messages", params={"limit": 200}, timeout=5)
    response.raise_for_status()
    messages: list[dict[str, Any]] = response.json().get("messages", [])
    return messages


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


@pytest.fixture(scope="session")
async def demo_apis() -> AsyncIterator[str]:
    """The Northwind demo APIs, served in process on a free port."""
    import asyncio

    import uvicorn

    from workflow_engine.demo.apis import create_app as demo_app

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(demo_app(), host="127.0.0.1", port=port, log_level="warning", lifespan="off")
    )
    task = asyncio.create_task(server.serve())
    while not server.started:  # noqa: ASYNC110 - uvicorn exposes a flag, not an event
        await asyncio.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    await task


@pytest.fixture(scope="session")
async def worker(container: Container, demo_apis: str) -> AsyncIterator[Any]:
    """A real executor and scheduler on the app's container, for the whole session."""
    import asyncio

    from workflow_engine.runtime.executor import Executor
    from workflow_engine.runtime.scheduler import Scheduler

    stopping = asyncio.Event()
    executor = Executor(container, "it-worker-1")
    scheduler = Scheduler(container, "it-worker-1")
    tasks = [
        asyncio.create_task(executor.run(stopping)),
        asyncio.create_task(scheduler.run(stopping)),
    ]
    yield executor
    stopping.set()
    await asyncio.gather(*tasks, return_exceptions=True)


TERMINAL = {"succeeded", "failed", "cancelled"}


async def wait_for(
    client: httpx.AsyncClient,
    account: Account,
    execution_id: str,
    statuses: set[str] | None = None,
    seconds: float = 20.0,
) -> dict[str, Any]:
    import asyncio
    import time

    wanted = statuses or TERMINAL
    deadline = time.monotonic() + seconds
    body: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = await client.get(
            f"/api/v1/workspaces/{account.workspace}/executions/{execution_id}",
            headers=account.headers,
        )
        body = response.json()
        if body.get("status") in wanted:
            return body
        await asyncio.sleep(0.1)
    raise AssertionError(f"execution {execution_id} stayed {body.get('status')}: {body}")
