"""`make demo`: a realistic Northwind Outfitters workspace with two weeks of real history.

Everything in the seeded history really ran: the seed sends signed webhooks, publishes
events and runs workflows through the engine, against the demo APIs, Floci (S3, SQS, SES)
and a read-only warehouse database. Once the executions have settled, their timestamps are
spread over the past `history_days` days so the dashboard has a shape. Executions still
waiting (the onboarding follow-ups) keep their real, recent times.

The data is fictional: Northwind and its people use example.com addresses.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import asyncpg
import orjson
from sqlalchemy import func, select, text

from workflow_engine.core.config import Settings
from workflow_engine.core.crypto import sign
from workflow_engine.core.logging import get_logger
from workflow_engine.demo.apis import COMPANIES, CUSTOMERS, INVENTORY, PRODUCTS, order
from workflow_engine.models import Event, Execution, Workflow, Workspace
from workflow_engine.models.enums import Role
from workflow_engine.repositories.users import UserRepository
from workflow_engine.runtime.executor import Executor
from workflow_engine.schemas.workspaces import WorkspaceSettings
from workflow_engine.services.container import Container, build_container
from workflow_engine.services.events import EventService
from workflow_engine.services.executions import ExecutionService
from workflow_engine.services.gallery import template
from workflow_engine.services.principal import Principal
from workflow_engine.services.users import create_user
from workflow_engine.services.variables import VariableService
from workflow_engine.services.vault import CredentialService
from workflow_engine.services.webhooks import WebhookService
from workflow_engine.services.workflows import WorkflowService
from workflow_engine.services.workspaces import WorkspaceService

log = get_logger("wfe.demo")
OWNER = ("Maya Patel", "maya@northwind.example.com")
PEOPLE = [
    ("Ravi Shah", "ravi@northwind.example.com", "editor"),
    ("Lena Fischer", "lena@northwind.example.com", "viewer"),
]
WORKSPACE_NAME = "Northwind Outfitters"
TIMEZONE = "Asia/Kolkata"
SETTLE_TIMEOUT_S = 240


@dataclass
class Demo:
    container: Container
    settings: Settings
    password: str
    principal: Principal
    workspace: Workspace
    workflows: dict[str, Workflow]


def derived(password: str, purpose: str, length: int = 32) -> str:
    """Demo secrets derived from the demo password: nothing secret lives in the source."""
    return hashlib.sha256(f"{password}:{purpose}".encode()).hexdigest()[:length]


async def run(settings: Settings, password: str, *, history_days: int = 14) -> None:
    container = build_container(settings, application_name="wfe-seed")
    try:
        async with container.db.session() as session:
            if await UserRepository(session).by_email(OWNER[1]) is not None:
                print("Demo data is already present.")
                print_logins(settings, password)
                return
        demo = await seed_people(container, settings, password)
        await seed_warehouse(settings, password)
        await seed_configuration(demo)
        await seed_workflows(demo)
        stopping = asyncio.Event()
        executor = Executor(container, "demo-seed")
        worker = asyncio.create_task(executor.run(stopping))
        try:
            await generate_history(demo)
            await settle(demo)
        finally:
            stopping.set()
            await worker
        await spread_history(demo, history_days)
        stale = [key async for key in container.redis.scan_iter(match="wfe:dash:*")]
        if stale:
            await container.redis.delete(*stale)
        print_logins(settings, password)
    finally:
        await container.close()


def print_logins(settings: Settings, password: str) -> None:
    print("")
    print(f"  Demo workspace  {WORKSPACE_NAME} (northwind)")
    print(f"  Sign in         {settings.web_url}")
    print(f"    {OWNER[1]:<32} owner")
    for _, email, role in PEOPLE:
        print(f"    {email:<32} {role}")
    print(f"  Password        {password}   (every demo account, from deploy/compose/.env)")
    print(f"  Shop webhook    POST {settings.hooks_base_url}/hooks/northwind/shop/orders")


async def seed_people(container: Container, settings: Settings, password: str) -> Demo:
    async with container.db.session() as session:
        owner = await create_user(
            session, email=OWNER[1], name=OWNER[0], password=password, is_admin=True
        )
        principal = Principal(user=owner)
        service = WorkspaceService(container, session)
        workspace = await service.create(
            principal,
            WORKSPACE_NAME,
            "Automations for orders, billing, sales and operations at Northwind Outfitters.",
        )
        workspace.slug = "northwind"
        workspace.settings = WorkspaceSettings(timezone=TIMEZONE, retention_days=30).model_dump()
        await session.commit()
        for name, email, role in PEOPLE:
            await create_user(session, email=email, name=name, password=password)
            await service.add_member(workspace, principal, email, name, Role(role))
        return Demo(container, settings, password, principal, workspace, {})


async def seed_warehouse(settings: Settings, password: str) -> None:
    """A separate `warehouse` database with a read-only login for the Postgres node."""
    parts = urlsplit(settings.database_url.replace("postgresql+asyncpg://", "postgresql://"))
    admin = await asyncpg.connect(
        host=parts.hostname,
        port=parts.port or 5432,
        user=parts.username,
        password=parts.password,
        database=parts.path.lstrip("/"),
    )
    try:
        if not await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = 'warehouse'"):
            await admin.execute("CREATE DATABASE warehouse")
        reader_password = derived(password, "warehouse")
        if await admin.fetchval("SELECT 1 FROM pg_roles WHERE rolname = 'warehouse_reader'"):
            await admin.execute(
                f"ALTER ROLE warehouse_reader WITH LOGIN PASSWORD '{reader_password}'"
            )
        else:
            await admin.execute(
                f"CREATE ROLE warehouse_reader WITH LOGIN PASSWORD '{reader_password}'"
            )
    finally:
        await admin.close()
    warehouse = await asyncpg.connect(
        host=parts.hostname,
        port=parts.port or 5432,
        user=parts.username,
        password=parts.password,
        database="warehouse",
    )
    try:
        await warehouse.execute(
            """
            CREATE TABLE IF NOT EXISTS inventory (
              sku text PRIMARY KEY, title text NOT NULL, on_hand int NOT NULL,
              reorder_point int NOT NULL, unit_cost numeric(10, 2) NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
              id text PRIMARY KEY, customer text NOT NULL, total numeric(10, 2) NOT NULL,
              status text NOT NULL, placed_at timestamptz NOT NULL
            );
            TRUNCATE inventory, orders;
            GRANT CONNECT ON DATABASE warehouse TO warehouse_reader;
            GRANT USAGE ON SCHEMA public TO warehouse_reader;
            GRANT SELECT ON ALL TABLES IN SCHEMA public TO warehouse_reader;
            """
        )
        await warehouse.executemany(
            "INSERT INTO inventory VALUES ($1, $2, $3, $4, $5)",
            [
                (sku, title, INVENTORY[sku], 10, round(price * 0.45, 2))
                for sku, title, price in PRODUCTS
            ],
        )
        rows = [order(n) for n in range(1, 41)]
        await warehouse.executemany(
            "INSERT INTO orders VALUES ($1, $2, $3, $4, $5)",
            [
                (
                    o["id"],
                    o["customer"]["name"],
                    o["total"],
                    o["status"],
                    datetime.fromisoformat(o["placed_at"]),
                )
                for o in rows
            ],
        )
    finally:
        await warehouse.close()


async def seed_configuration(demo: Demo) -> None:
    base = demo.settings.demo_apis_url.rstrip("/")
    variables = {
        "SHOP_API": (f"{base}/shop", "The Northwind shop API"),
        "FULFILLMENT_API": (f"{base}/fulfillment", "Creates shipments"),
        "CRM_API": (f"{base}/crm", "Company enrichment and lead assignment"),
        "BILLING_API": (f"{base}/billing", "Invoices and the payment gateway"),
        "STATUS_API": (f"{base}/status", "Service status checks"),
        "OPS_EMAIL": ("ops@northwind.example.com", "Operations team"),
        "SALES_EMAIL": ("sales@northwind.example.com", "Account executives"),
        "FINANCE_EMAIL": ("finance@northwind.example.com", "Finance team"),
        "ONCALL_EMAIL": ("oncall@northwind.example.com", "On-call rotation"),
    }
    host = urlsplit(demo.settings.database_url.replace("postgresql+asyncpg://", "postgresql://"))
    async with demo.container.db.session() as session:
        service = VariableService(session)
        for key, (value, description) in variables.items():
            await service.put(demo.workspace.id, demo.principal, key, value, description)
        vault = CredentialService(demo.container, session)
        credentials: list[tuple[str, str, str, dict[str, Any]]] = [
            (
                "Shop webhook secret",
                "webhook_secret",
                "Signs paid-order webhooks from the shop",
                {"secret": "whsec_" + derived(demo.password, "shop")},
            ),
            (
                "Signup webhook token",
                "webhook_secret",
                "Bearer token for the sign-up form",
                {"secret": "tok_" + derived(demo.password, "signup")},
            ),
            ("Sales Slack", "slack_webhook", "#sales", {"url": f"{base}/slack/sales"}),
            (
                "Enterprise Slack",
                "slack_webhook",
                "#enterprise-sales",
                {"url": f"{base}/slack/enterprise-sales"},
            ),
            ("Ops Slack", "slack_webhook", "#ops-alerts", {"url": f"{base}/slack/ops-alerts"}),
            ("On-call Slack", "slack_webhook", "#on-call", {"url": f"{base}/slack/on-call"}),
            (
                "Warehouse database",
                "postgres",
                "Read-only login to the warehouse reporting database",
                {
                    "host": host.hostname or "localhost",
                    "port": host.port or 5432,
                    "database": "warehouse",
                    "user": "warehouse_reader",
                    "password": derived(demo.password, "warehouse"),
                    "ssl_mode": "disable",
                },
            ),
        ]
        for name, kind, description, data in credentials:
            await vault.create(
                demo.workspace.id,
                demo.principal,
                name=name,
                kind=kind,
                description=description,
                data=data,
            )


async def seed_workflows(demo: Demo) -> None:
    async with demo.container.db.session() as session:
        service = WorkflowService(demo.container, session)
        for slug in (
            "order-fulfillment",
            "lead-routing",
            "invoice-batch",
            "uptime-monitor",
            "low-stock-report",
            "failure-alerts",
            "customer-onboarding",
        ):
            workflow, missing = await service.create_from_template(
                demo.workspace, demo.principal, slug
            )
            if missing:
                raise RuntimeError(f"{slug}: missing credentials {missing}")
            limit = template(slug).settings.get("concurrency_limit")
            if limit:
                workflow.concurrency_limit = int(limit)
                await session.commit()
            await service.publish(
                demo.workspace, demo.principal, workflow.id, note="First version", activate=True
            )
            demo.workflows[slug] = workflow
        # A second version, so the version history has something to show.
        order_flow = demo.workflows["order-fulfillment"]
        await session.refresh(order_flow)
        draft = dict(order_flow.draft)
        for node in draft["nodes"]:
            if node["id"] == "create_shipment":
                node["config"]["timeout_s"] = 20
        await service.save_draft(
            demo.workspace.id, demo.principal, order_flow.id, draft, order_flow.draft_revision
        )
        await service.publish(
            demo.workspace,
            demo.principal,
            order_flow.id,
            note="Allow the fulfillment API 20 s",
            activate=False,
        )
        draft_only = await service.create(
            demo.workspace,
            demo.principal,
            name="Quarterly price review",
            description="Work in progress: compare supplier prices with the catalog.",
            tags=["draft", "pricing"],
        )
        demo.workflows["draft"] = draft_only


async def _webhook(demo: Demo, path: str, body: dict[str, Any], headers: dict[str, str]) -> None:
    raw = orjson.dumps(body)
    async with demo.container.db.session() as session:
        await WebhookService(demo.container, session).receive(
            workspace_slug="northwind",
            path=path,
            method="POST",
            headers={"content-type": "application/json", **headers},
            query={},
            body=raw,
        )


async def generate_history(demo: Demo) -> None:
    rng = random.Random(2026)
    shop_secret = "whsec_" + derived(demo.password, "shop")
    for number in range(1, 33):
        placed = order(number)
        payload = {
            # Three orders arrive without an id; fulfillment refuses them (422, not retried).
            "order_id": "" if number in (9, 21, 30) else placed["id"],
            "customer": placed["customer"],
            "items": placed["items"],
            "total": placed["total"],
        }
        raw = orjson.dumps(payload)
        headers = {
            "x-shop-signature": sign(shop_secret, raw),
            "idempotency-key": f"evt_order_{number}",
        }
        await _webhook(demo, "shop/orders", payload, headers)
        if number == 12:
            await _webhook(
                demo, "shop/orders", payload, headers
            )  # a retried delivery: deduplicated
    domains = [*COMPANIES, "unknown-startup.example.com"]
    async with demo.container.db.session() as session:
        events = EventService(demo.container, session)
        for index in range(24):
            name, email, _ = CUSTOMERS[index % len(CUSTOMERS)]
            domain = domains[index % len(domains)]
            await events.publish(
                demo.workspace.id,
                demo.principal,
                "lead.created",
                {"lead_id": f"L-{300 + index}", "name": name, "email": email, "domain": domain},
            )
    now = datetime.now(UTC)
    async with demo.container.db.session() as session:
        executions = ExecutionService(demo.container, session)
        for slot in range(56):
            moment = now - timedelta(minutes=15 * rng.randint(4, 14 * 96))
            await executions.run(
                demo.workspace.id,
                demo.principal,
                demo.workflows["uptime-monitor"].id,
                payload={
                    "scheduled_for": moment.isoformat(timespec="seconds"),
                    "fired_at": moment.isoformat(timespec="seconds"),
                },
                use_draft=False,
                trigger_node=None,
                idempotency_key=f"seed-uptime-{slot}",
            )
        for slot in range(7):
            await executions.run(
                demo.workspace.id,
                demo.principal,
                demo.workflows["invoice-batch"].id,
                payload={"scheduled_for": (now - timedelta(days=slot)).isoformat()},
                use_draft=False,
                trigger_node=None,
                idempotency_key=f"seed-invoices-{slot}",
            )
        for slot in range(9):
            await executions.run(
                demo.workspace.id,
                demo.principal,
                demo.workflows["low-stock-report"].id,
                payload={"scheduled_for": (now - timedelta(days=slot)).isoformat()},
                use_draft=False,
                trigger_node=None,
                idempotency_key=f"seed-stock-{slot}",
            )
    signup_token = "tok_" + derived(demo.password, "signup")
    for index, (name, email, _) in enumerate(CUSTOMERS[:5]):
        domain = email.split("@")[1]
        await _webhook(
            demo,
            "signups",
            {"name": name, "email": email, "domain": domain},
            {"authorization": f"Bearer {signup_token}", "idempotency-key": f"signup-{index}"},
        )


async def settle(demo: Demo) -> None:
    deadline = asyncio.get_running_loop().time() + SETTLE_TIMEOUT_S
    while asyncio.get_running_loop().time() < deadline:
        async with demo.container.db.session() as session:
            busy = await session.scalar(
                select(func.count())
                .select_from(Execution)
                .where(
                    Execution.workspace_id == demo.workspace.id,
                    Execution.status.in_(("queued", "running")),
                )
            )
        if not busy:
            break
        await asyncio.sleep(1)
    async with demo.container.db.session() as session:
        service = ExecutionService(demo.container, session)
        letters, _ = await service.dead_letters(
            demo.workspace.id, status="open", limit=10, cursor=None
        )
        if letters:
            await service.discard(demo.workspace.id, demo.principal, letters[-1][0].id)
        waiting = (
            await session.execute(
                select(Execution.id)
                .where(Execution.workspace_id == demo.workspace.id, Execution.status == "waiting")
                .order_by(Execution.created_at)
                .limit(1)
            )
        ).scalar_one_or_none()
        if waiting is not None:
            await service.cancel(demo.workspace.id, demo.principal, waiting)


def _targets(count: int, days: int, now: datetime, rng: random.Random) -> list[datetime]:
    """Business-hours times over the window, a little busier towards today, oldest first."""
    moments = []
    for _ in range(count):
        day = int(days * (1 - rng.random() ** 1.6))
        hour = rng.choice([8, 9, 9, 10, 11, 11, 12, 13, 14, 15, 15, 16, 17, 18, 20, 22])
        moment = (now - timedelta(days=day)).replace(
            hour=hour, minute=rng.randint(0, 59), second=rng.randint(0, 59)
        )
        moments.append(min(moment, now - timedelta(minutes=5)))
    return sorted(moments)


async def spread_history(demo: Demo, days: int) -> None:
    rng = random.Random(7)
    now = datetime.now(UTC)
    async with demo.container.db.session() as session:
        rows = (
            await session.execute(
                select(Execution, Event.source, Event.source_execution_id)
                .outerjoin(Event, Event.id == Execution.event_id)
                .where(Execution.workspace_id == demo.workspace.id)
                .order_by(Execution.created_at)
            )
        ).all()
        deltas: dict[Any, timedelta] = {}
        by_workflow: dict[Any, list[Execution]] = {}
        followers: list[tuple[Execution, Any]] = []
        for execution, source, source_execution in rows:
            if (
                execution.status == "waiting"
                or execution.workflow_id == demo.workflows["customer-onboarding"].id
            ):
                continue
            if source == "system" and source_execution is not None:
                followers.append((execution, source_execution))
                continue
            by_workflow.setdefault(execution.workflow_id, []).append(execution)
        for executions in by_workflow.values():
            uptime = executions[0].workflow_id == demo.workflows["uptime-monitor"].id
            targets = _targets(len(executions), days, now, rng)
            for execution, target in zip(executions, targets, strict=True):
                if uptime and isinstance(execution.trigger_payload, dict):
                    target = datetime.fromisoformat(str(execution.trigger_payload["scheduled_for"]))
                deltas[execution.id] = target - execution.created_at
        for execution, source_execution in followers:
            deltas[execution.id] = deltas.get(source_execution, timedelta(0))
        for execution_id, delta in deltas.items():
            params = {"id": execution_id, "delta": delta}
            await session.execute(
                text(
                    "UPDATE executions SET created_at = created_at + :delta, "
                    "updated_at = updated_at + :delta, started_at = started_at + :delta, "
                    "finished_at = finished_at + :delta, deadline_at = deadline_at + :delta "
                    "WHERE id = :id"
                ),
                params,
            )
            await session.execute(
                text(
                    "UPDATE execution_steps SET created_at = created_at + :delta, "
                    "updated_at = updated_at + :delta, "
                    "started_at = started_at + :delta, finished_at = finished_at + :delta, "
                    "available_at = available_at + :delta, locked_at = locked_at + :delta, "
                    "heartbeat_at = heartbeat_at + :delta WHERE execution_id = :id"
                ),
                params,
            )
            await session.execute(
                text(
                    "UPDATE execution_logs SET created_at = created_at + :delta "
                    "WHERE execution_id = :id"
                ),
                params,
            )
            await session.execute(
                text(
                    "UPDATE dead_letters SET created_at = created_at + :delta, "
                    "resolved_at = resolved_at + :delta WHERE execution_id = :id"
                ),
                params,
            )
            await session.execute(
                text(
                    "UPDATE events SET created_at = created_at + :delta WHERE id = "
                    "(SELECT event_id FROM executions WHERE id = :id AND event_id IS NOT NULL)"
                ),
                params,
            )
        await session.commit()
    log.info("history_spread", executions=len(deltas), days=days)
