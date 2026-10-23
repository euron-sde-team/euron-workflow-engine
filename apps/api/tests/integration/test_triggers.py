"""Webhooks (HMAC, tokens, idempotency, response modes), the event bus and schedules."""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import orjson
import pytest
from sqlalchemy import select, update

from tests.integration.conftest import Account, wait_for
from tests.integration.helpers import (
    base,
    create_workflow,
    credential,
    edge,
    node,
    publish,
    steps_by_node,
)
from workflow_engine.core.crypto import sign
from workflow_engine.models import Execution, WorkflowTrigger
from workflow_engine.services import sweeps
from workflow_engine.services.container import Container

pytestmark = pytest.mark.usefixtures("worker")
SECRET = "whsec_integration_0123456789"


async def _hooked(
    client: httpx.AsyncClient, owner: Account, path: str, **config: object
) -> dict[str, object]:
    secret_id = await credential(
        client, owner, f"Hook secret {path}", "webhook_secret", secret=SECRET
    )
    nodes = [
        node("hook", "trigger.webhook", {"path": path, "credential_id": secret_id, **config}),
        node(
            "reply",
            "core.transform",
            {"expression": "{order: trigger.body.order_id, total: trigger.body.total}"},
        ),
    ]
    workflow = await create_workflow(client, owner, f"Hook {path}", nodes, [edge("hook", "reply")])
    return await publish(client, owner, str(workflow["id"]))


async def test_signed_webhooks_start_executions_once_per_idempotency_key(
    client: httpx.AsyncClient, owner: Account
) -> None:
    await _hooked(client, owner, "orders/created")
    url = f"/hooks/{owner.workspace}/orders/created"
    body = orjson.dumps({"order_id": "SO-1042", "total": 129.5})
    unsigned = await client.post(url, content=body, headers={"content-type": "application/json"})
    assert unsigned.status_code == 401
    assert unsigned.json()["error"]["code"] == "missing_signature"
    forged = await client.post(
        url,
        content=body,
        headers={"content-type": "application/json", "x-signature": sign("wrong-secret", body)},
    )
    assert forged.json()["error"]["code"] == "invalid_signature"
    headers = {
        "content-type": "application/json",
        "x-signature": sign(SECRET, body),
        "idempotency-key": "evt_1",
    }
    accepted = await client.post(url, content=body, headers=headers)
    assert accepted.status_code == 202, accepted.text
    duplicate = await client.post(url, content=body, headers=headers)
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["execution_id"] == accepted.json()["execution_id"]
    execution = await wait_for(client, owner, accepted.json()["execution_id"])
    assert execution["output"] == {"order": "SO-1042", "total": 129.5}
    assert execution["trigger_kind"] == "webhook"
    assert "x-signature" not in execution["trigger_payload"]["headers"]
    # Verifying a signature counts as using the secret.
    stored = await client.get(f"{base(owner)}/credentials", headers=owner.headers)
    secret = next(c for c in stored.json() if c["name"] == "Hook secret orders/created")
    assert secret["last_used_at"] is not None
    wrong_method = await client.get(url)
    assert wrong_method.status_code == 405
    unknown = await client.post(f"/hooks/{owner.workspace}/nope", content=b"{}")
    assert unknown.status_code == 404


async def test_timestamped_signatures_refuse_replays(
    client: httpx.AsyncClient, owner: Account
) -> None:
    await _hooked(client, owner, "payments", timestamp_header="X-Timestamp", tolerance_s=60)
    url = f"/hooks/{owner.workspace}/payments"
    body = b'{"order_id": "SO-7", "total": 10}'
    now = str(int(time.time()))
    fresh = await client.post(
        url,
        content=body,
        headers={
            "content-type": "application/json",
            "x-timestamp": now,
            "x-signature": sign(SECRET, body, timestamp=now),
        },
    )
    assert fresh.status_code == 202, fresh.text
    old = str(int(time.time()) - 3600)
    replay = await client.post(
        url,
        content=body,
        headers={
            "content-type": "application/json",
            "x-timestamp": old,
            "x-signature": sign(SECRET, body, timestamp=old),
        },
    )
    assert replay.json()["error"]["code"] == "stale_request"
    moved = await client.post(
        url,
        content=body,
        headers={
            "content-type": "application/json",
            "x-timestamp": now,
            "x-signature": sign(SECRET, body),
        },
    )
    assert moved.json()["error"]["code"] == "invalid_signature"


async def test_bearer_webhooks_and_synchronous_responses(
    client: httpx.AsyncClient, owner: Account
) -> None:
    await _hooked(
        client, owner, "quote", auth="bearer", response="when_finished", response_timeout_s=10
    )
    url = f"/hooks/{owner.workspace}/quote"
    denied = await client.post(
        url, json={"order_id": "Q-1", "total": 5}, headers={"authorization": "Bearer nope"}
    )
    assert denied.status_code == 401
    answered = await client.post(
        url, json={"order_id": "Q-1", "total": 5}, headers={"authorization": f"Bearer {SECRET}"}
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["status"] == "succeeded"
    assert answered.json()["output"] == {"order": "Q-1", "total": 5}


async def test_events_start_subscribed_workflows_with_filters(
    client: httpx.AsyncClient, owner: Account
) -> None:
    listener = await create_workflow(
        client,
        owner,
        "Big leads",
        [
            node(
                "on_lead",
                "trigger.event",
                {"event": "lead.*", "filter": "payload.employees > `500`"},
            ),
            node("note", "core.transform", {"expression": "trigger.payload.company"}),
        ],
        [edge("on_lead", "note")],
    )
    await publish(client, owner, str(listener["id"]))
    small = await client.post(
        f"{base(owner)}/events",
        json={"name": "lead.created", "payload": {"company": "Harborview", "employees": 18}},
        headers=owner.headers,
    )
    assert small.status_code == 201
    assert small.json()["matched"] == 0
    big = await client.post(
        f"{base(owner)}/events",
        json={"name": "lead.created", "payload": {"company": "Summit Works", "employees": 5400}},
        headers=owner.headers,
    )
    assert big.json()["matched"] == 1
    execution = await wait_for(client, owner, str(big.json()["executions"][0]))
    assert execution["output"] == "Summit Works"
    assert execution["trigger_kind"] == "event"
    events = (await client.get(f"{base(owner)}/events?name=lead.", headers=owner.headers)).json()[
        "items"
    ]
    assert [e["matched"] for e in events[:2]] == [1, 0]


async def test_workflows_chain_through_events_and_failures_raise_system_events(
    client: httpx.AsyncClient, owner: Account
) -> None:
    handler = await create_workflow(
        client,
        owner,
        "Failure handler",
        [
            node("on_failure", "trigger.event", {"event": "execution.failed"}),
            node("note", "core.transform", {"expression": "trigger.payload.workflow_name"}),
        ],
        [edge("on_failure", "note")],
    )
    await publish(client, owner, str(handler["id"]))
    downstream = await create_workflow(
        client,
        owner,
        "Invoice consumer",
        [
            node("on_invoice", "trigger.event", {"event": "invoice.created"}),
            node(
                "boom",
                "flow.stop",
                {"code": "rejected", "message": "Invoice {{ trigger.payload.id }} rejected"},
            ),
        ],
        [edge("on_invoice", "boom")],
    )
    await publish(client, owner, str(downstream["id"]))
    producer = await create_workflow(
        client,
        owner,
        "Invoice producer",
        [
            node("start", "trigger.manual"),
            node("emit", "event.emit", {"event": "invoice.created", "payload": {"id": "INV-9"}}),
        ],
        [edge("start", "emit")],
    )
    await publish(client, owner, str(producer["id"]))
    started = await client.post(
        f"{base(owner)}/workflows/{producer['id']}/run", json={}, headers=owner.headers
    )
    produced = await wait_for(client, owner, started.json()["execution_id"])
    assert produced["output"]["matched"] == 1
    for _ in range(100):
        listing = (
            await client.get(
                f"{base(owner)}/executions?workflow_id={handler['id']}", headers=owner.headers
            )
        ).json()["items"]
        if listing and listing[0]["status"] == "succeeded":
            break
        await asyncio.sleep(0.1)
    handled = await wait_for(client, owner, listing[0]["id"])
    assert handled["output"] == "Invoice consumer"
    consumer = (
        await client.get(
            f"{base(owner)}/executions?workflow_id={downstream['id']}", headers=owner.headers
        )
    ).json()["items"][0]
    assert consumer["error"]["message"] == "Invoice INV-9 rejected"
    # The system event links to the failed run in the web app, inside its workspace.
    link = handled["trigger_payload"]["payload"]["url"]
    assert link.endswith(f"/w/{owner.workspace}/executions/{consumer['id']}")
    # The handler itself never raises execution.* events, so it cannot loop.
    await asyncio.sleep(0.5)
    again = (
        await client.get(
            f"{base(owner)}/executions?workflow_id={handler['id']}", headers=owner.headers
        )
    ).json()["items"]
    assert len(again) == 1


async def test_schedules_fire_once_per_tick_even_with_two_schedulers(
    client: httpx.AsyncClient, owner: Account, container: Container
) -> None:
    workflow = await create_workflow(
        client,
        owner,
        "Nightly report",
        [
            node(
                "nightly", "trigger.cron", {"expression": "0 2 * * *", "timezone": "Europe/Berlin"}
            ),
            node("note", "core.transform", {"expression": "trigger.scheduled_for"}),
        ],
        [edge("nightly", "note")],
    )
    await publish(client, owner, str(workflow["id"]))
    workflow_id = uuid.UUID(str(workflow["id"]))
    due = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=3)
    async with container.db.session() as session:
        await session.execute(
            update(WorkflowTrigger)
            .where(WorkflowTrigger.workflow_id == workflow_id)
            .values(next_fire_at=due)
        )
        await session.commit()
    now = datetime.now(UTC)
    await asyncio.gather(
        sweeps.fire_schedules(container, now), sweeps.fire_schedules(container, now)
    )
    for _ in range(50):
        async with container.db.session() as session:
            rows = (
                (
                    await session.execute(
                        select(Execution).where(Execution.workflow_id == workflow_id)
                    )
                )
                .scalars()
                .all()
            )
        if rows and rows[0].status == "succeeded":
            break
        await asyncio.sleep(0.1)
    assert len(rows) == 1
    assert rows[0].trigger_kind == "cron"
    trigger = await _trigger(container, workflow_id)
    tick = due.isoformat().replace("+00:00", "Z")
    assert rows[0].idempotency_key == f"schedule:{trigger.id}:{tick}"
    assert trigger.last_fired_at == due
    assert trigger.next_fire_at is not None
    assert trigger.next_fire_at > now
    assert trigger.next_fire_at.astimezone(UTC).hour in (0, 1)  # 02:00 in Berlin


async def _trigger(container: Container, workflow_id: uuid.UUID) -> WorkflowTrigger:
    async with container.db.session() as session:
        return (
            await session.execute(
                select(WorkflowTrigger).where(WorkflowTrigger.workflow_id == workflow_id)
            )
        ).scalar_one()


async def test_overlap_skip_does_not_stack_runs(
    client: httpx.AsyncClient, owner: Account, container: Container, demo_apis: str
) -> None:
    workflow = await create_workflow(
        client,
        owner,
        "No overlap",
        [
            node("tick", "trigger.interval", {"every": 10, "unit": "seconds", "overlap": "skip"}),
            node("slow", "http.request", {"url": f"{demo_apis}/slow?seconds=2"}),
        ],
        [edge("tick", "slow")],
    )
    await publish(client, owner, str(workflow["id"]))
    workflow_id = uuid.UUID(str(workflow["id"]))
    for _ in range(2):
        async with container.db.session() as session:
            await session.execute(
                update(WorkflowTrigger)
                .where(WorkflowTrigger.workflow_id == workflow_id)
                .values(next_fire_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            await session.commit()
        await sweeps.fire_schedules(container, datetime.now(UTC))
    async with container.db.session() as session:
        rows = (
            (await session.execute(select(Execution).where(Execution.workflow_id == workflow_id)))
            .scalars()
            .all()
        )
    assert len(rows) == 1
    await client.post(f"{base(owner)}/workflows/{workflow_id}/deactivate", headers=owner.headers)
    finished = await wait_for(client, owner, str(rows[0].id))
    assert steps_by_node(finished)["slow"][0]["status"] == "succeeded"
