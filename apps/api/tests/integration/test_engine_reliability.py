"""Failure handling: retries, dead letters, resume, timeouts, cancellation, limits, reaping."""

from __future__ import annotations

import asyncio
import itertools
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, update

from tests.integration.conftest import Account, wait_for
from tests.integration.helpers import base, create_workflow, edge, node, publish, run, steps_by_node
from workflow_engine.models import Execution, ExecutionStep
from workflow_engine.repositories.executions import StepRepository
from workflow_engine.runtime.leader import LeaderElection
from workflow_engine.services.container import Container

pytestmark = pytest.mark.usefixtures("worker")
FAST_RETRY = {
    "max_attempts": 3,
    "initial_delay_ms": 100,
    "max_delay_ms": 400,
    "multiplier": 2,
    "jitter": False,
}


async def test_transient_failures_retry_with_backoff(
    client: httpx.AsyncClient, owner: Account, demo_apis: str
) -> None:
    key = uuid.uuid4().hex
    nodes = [
        node("start", "trigger.manual"),
        node("call", "http.request", {"url": f"{demo_apis}/flaky/{key}?fail=2"}, retry=FAST_RETRY),
    ]
    workflow = await create_workflow(client, owner, "Flaky", nodes, [edge("start", "call")])
    execution = await wait_for(
        client, owner, (await run(client, owner, workflow["id"], draft=True))["execution_id"]
    )
    assert execution["status"] == "succeeded", execution
    call = steps_by_node(execution)["call"][0]
    assert call["attempt"] == 3
    assert execution["output"]["body"] == {"attempt": 3, "ok": True}
    logs = (
        await client.get(f"{base(owner)}/executions/{execution['id']}/logs", headers=owner.headers)
    ).json()["items"]
    retries = [line["message"] for line in logs if "retrying in" in line["message"]]
    assert retries == [
        "Attempt 1 of 3 failed (http_503); retrying in 0.1 s",
        "Attempt 2 of 3 failed (http_503); retrying in 0.2 s",
    ]


async def test_exhausted_retries_park_a_dead_letter_and_resume_continues(
    client: httpx.AsyncClient, owner: Account, demo_apis: str
) -> None:
    key = uuid.uuid4().hex
    nodes = [
        node("start", "trigger.manual"),
        node("prepare", "core.transform", {"mode": "template", "template": {"ready": True}}),
        node(
            "call",
            "http.request",
            {"url": f"{demo_apis}/flaky/{key}?fail=2"},
            retry={**FAST_RETRY, "max_attempts": 2},
        ),
        node(
            "after",
            "core.transform",
            {"expression": "{status: input.status, prepared: steps.prepare.ready}"},
        ),
    ]
    workflow = await create_workflow(
        client,
        owner,
        "Resumable",
        nodes,
        [edge("start", "prepare"), edge("prepare", "call"), edge("call", "after")],
    )
    execution = await wait_for(
        client, owner, (await run(client, owner, workflow["id"], draft=True))["execution_id"]
    )
    assert execution["status"] == "failed"
    assert execution["error"]["code"] == "http_503"
    assert execution["error"]["node_id"] == "call"
    letters = (await client.get(f"{base(owner)}/dead-letters", headers=owner.headers)).json()[
        "items"
    ]
    letter = next(item for item in letters if item["execution_id"] == execution["id"])
    assert letter["status"] == "open"
    assert letter["node_name"] == "Call"

    resumed = await client.post(
        f"{base(owner)}/dead-letters/{letter['id']}/retry", headers=owner.headers
    )
    assert resumed.status_code == 200, resumed.text
    finished = await wait_for(client, owner, execution["id"])
    assert finished["status"] == "succeeded", finished
    assert finished["resume_count"] == 1
    assert finished["output"] == {"status": 200, "prepared": True}
    grouped = steps_by_node(finished)
    assert len(grouped["prepare"]) == 1  # the step that succeeded did not run again
    assert grouped["call"][0]["attempt"] == 3
    after = (
        await client.get(f"{base(owner)}/dead-letters?status=retried", headers=owner.headers)
    ).json()["items"]
    assert any(item["id"] == letter["id"] for item in after)
    again = await client.post(
        f"{base(owner)}/executions/{execution['id']}/resume", headers=owner.headers
    )
    assert again.status_code == 409


async def test_on_error_continue_routes_the_error_onward(
    client: httpx.AsyncClient, owner: Account
) -> None:
    nodes = [
        node("start", "trigger.manual"),
        node("risky", "core.transform", {"expression": "upper(input)"}, on_error="continue"),
        node("after", "core.transform", {"expression": "{code: input.error.code}"}),
    ]
    workflow = await create_workflow(
        client, owner, "Continue on error", nodes, [edge("start", "risky"), edge("risky", "after")]
    )
    execution = await wait_for(
        client,
        owner,
        (await run(client, owner, workflow["id"], {"a": 1}, draft=True))["execution_id"],
    )
    assert execution["status"] == "succeeded"
    assert execution["output"] == {"code": "expression_error"}
    assert steps_by_node(execution)["risky"][0]["status"] == "failed"


async def test_slow_steps_time_out(
    client: httpx.AsyncClient, owner: Account, demo_apis: str
) -> None:
    nodes = [
        node("start", "trigger.manual"),
        node(
            "slow",
            "http.request",
            {"url": f"{demo_apis}/slow?seconds=5"},
            timeout_s=1,
            retry={"max_attempts": 1},
        ),
    ]
    workflow = await create_workflow(client, owner, "Slow", nodes, [edge("start", "slow")])
    execution = await wait_for(
        client, owner, (await run(client, owner, workflow["id"], draft=True))["execution_id"]
    )
    assert execution["status"] == "failed"
    assert execution["error"]["code"] == "timeout"


async def test_waits_suspend_without_a_worker_and_wake_on_time(
    client: httpx.AsyncClient, owner: Account
) -> None:
    nodes = [
        node("start", "trigger.manual"),
        node("pause", "flow.wait", {"amount": 1, "unit": "seconds"}),
        node("after", "core.transform", {"expression": '`"woke"`'}),
    ]
    workflow = await create_workflow(
        client, owner, "Short wait", nodes, [edge("start", "pause"), edge("pause", "after")]
    )
    started = await run(client, owner, workflow["id"], draft=True)
    waiting = await wait_for(client, owner, started["execution_id"], {"waiting"}, seconds=5)
    assert steps_by_node(waiting)["pause"][0]["status"] == "waiting"
    finished = await wait_for(client, owner, started["execution_id"], seconds=10)
    assert finished["status"] == "succeeded"
    assert finished["output"] == "woke"


async def test_cancelling_a_waiting_execution(client: httpx.AsyncClient, owner: Account) -> None:
    nodes = [
        node("start", "trigger.manual"),
        node("pause", "flow.wait", {"amount": 1, "unit": "hours"}),
    ]
    workflow = await create_workflow(client, owner, "Long wait", nodes, [edge("start", "pause")])
    started = await run(client, owner, workflow["id"], draft=True)
    await wait_for(client, owner, started["execution_id"], {"waiting"}, seconds=5)
    cancelled = await client.post(
        f"{base(owner)}/executions/{started['execution_id']}/cancel", headers=owner.headers
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    detail = await wait_for(client, owner, started["execution_id"])
    assert steps_by_node(detail)["pause"][0]["status"] == "cancelled"
    again = await client.post(
        f"{base(owner)}/executions/{started['execution_id']}/cancel", headers=owner.headers
    )
    assert again.status_code == 409


async def test_cancelling_a_running_step_stops_it(
    client: httpx.AsyncClient, owner: Account, demo_apis: str
) -> None:
    nodes = [
        node("start", "trigger.manual"),
        node("slow", "http.request", {"url": f"{demo_apis}/slow?seconds=8"}, timeout_s=30),
    ]
    workflow = await create_workflow(
        client, owner, "Cancel running", nodes, [edge("start", "slow")]
    )
    started = await run(client, owner, workflow["id"], draft=True)
    await asyncio.sleep(0.8)
    await client.post(
        f"{base(owner)}/executions/{started['execution_id']}/cancel", headers=owner.headers
    )
    detail = await wait_for(client, owner, started["execution_id"])
    assert detail["status"] == "cancelled"
    assert steps_by_node(detail)["slow"][0]["status"] == "cancelled"


async def test_concurrency_limits_queue_executions(
    client: httpx.AsyncClient, owner: Account, demo_apis: str
) -> None:
    nodes = [
        node("start", "trigger.manual"),
        node("work", "http.request", {"url": f"{demo_apis}/slow?seconds=0.6"}),
    ]
    workflow = await create_workflow(
        client, owner, "One at a time", nodes, [edge("start", "work")], concurrency_limit=1
    )
    await publish(client, owner, workflow["id"], activate=False)
    ids = [(await run(client, owner, workflow["id"]))["execution_id"] for _ in range(3)]
    listing = (
        await client.get(
            f"{base(owner)}/executions?workflow_id={workflow['id']}", headers=owner.headers
        )
    ).json()["items"]
    assert sorted(e["status"] for e in listing).count("queued") >= 1
    finished = [await wait_for(client, owner, execution_id, seconds=20) for execution_id in ids]
    assert all(e["status"] == "succeeded" for e in finished)
    spans = sorted(
        (datetime.fromisoformat(e["started_at"]), datetime.fromisoformat(e["finished_at"]))
        for e in finished
    )
    for (_, end), (start, _) in itertools.pairwise(spans):
        assert start >= end - timedelta(milliseconds=50), spans


async def test_retry_from_start_creates_a_new_execution(
    client: httpx.AsyncClient, owner: Account
) -> None:
    workflow = await create_workflow(
        client,
        owner,
        "Retry me",
        [node("start", "trigger.manual"), node("boom", "flow.stop", {"message": "no"})],
        [edge("start", "boom")],
    )
    first = await wait_for(
        client,
        owner,
        (await run(client, owner, workflow["id"], {"x": 1}, draft=True))["execution_id"],
    )
    assert first["error"]["code"] == "stopped"
    retried = await client.post(
        f"{base(owner)}/executions/{first['id']}/retry", headers=owner.headers
    )
    assert retried.status_code == 201
    second = await wait_for(client, owner, retried.json()["execution_id"])
    assert second["retry_of_id"] == first["id"]
    assert second["trigger_kind"] == "retry"
    assert second["trigger_payload"] == {"x": 1}


async def test_oversized_outputs_fail_the_step(
    client: httpx.AsyncClient, owner: Account, container: Container
) -> None:
    half = container.settings.max_payload_kb * 1024 // 2 + 1024
    nodes = [
        node("start", "trigger.manual"),
        node("double", "core.transform", {"expression": "[input, input]"}),
    ]
    workflow = await create_workflow(client, owner, "Too big", nodes, [edge("start", "double")])
    started = await run(client, owner, workflow["id"], {"blob": "x" * half}, draft=True)
    execution = await wait_for(client, owner, started["execution_id"])
    assert execution["error"]["code"] == "payload_too_large"


async def test_steps_of_a_lost_worker_are_reaped_and_retried(
    client: httpx.AsyncClient, owner: Account, container: Container, worker: object
) -> None:
    nodes = [
        node("start", "trigger.manual"),
        node("pause", "flow.wait", {"amount": 1, "unit": "hours"}),
    ]
    workflow = await create_workflow(
        client,
        owner,
        "Ghost",
        [*nodes, node("work", "core.transform", {"expression": "`1`"})],
        [edge("start", "work")],
    )
    started = await run(client, owner, workflow["id"], draft=True)
    execution_id = uuid.UUID(started["execution_id"])
    # Pretend a worker claimed the step and died: lock it under another name, stale heartbeat.
    async with container.db.session() as session:
        await session.execute(
            update(ExecutionStep)
            .where(ExecutionStep.execution_id == execution_id, ExecutionStep.node_id == "work")
            .values(
                status="running",
                locked_by="ghost-worker",
                attempt=1,
                max_attempts=2,
                heartbeat_at=datetime.now(UTC) - timedelta(minutes=5),
            )
        )
        await session.commit()
    finished = await wait_for(client, owner, str(execution_id), seconds=15)
    assert finished["status"] == "succeeded", finished
    logs = (
        await client.get(f"{base(owner)}/executions/{execution_id}/logs", headers=owner.headers)
    ).json()["items"]
    assert any("ghost-worker stopped sending heartbeats" in line["message"] for line in logs)


async def test_racing_workers_never_claim_a_step_twice(
    client: httpx.AsyncClient, owner: Account, container: Container
) -> None:
    nodes = [
        node("start", "trigger.manual"),
        *[node(f"n{i}", "flow.wait", {"amount": 1, "unit": "hours"}) for i in range(40)],
    ]
    workflow = await create_workflow(
        client, owner, "Race", nodes, [edge("start", f"n{i}") for i in range(40)]
    )
    started = await run(client, owner, workflow["id"], draft=True)
    execution_id = uuid.UUID(started["execution_id"])
    await wait_for(client, owner, str(execution_id), {"waiting"}, seconds=10)
    async with container.db.session() as session:
        await session.execute(
            update(ExecutionStep)
            .where(ExecutionStep.execution_id == execution_id, ExecutionStep.node_id != "start")
            .values(status="queued", available_at=datetime.now(UTC) + timedelta(hours=1))
        )
        await session.commit()
        await session.execute(
            update(ExecutionStep)
            .where(ExecutionStep.execution_id == execution_id, ExecutionStep.node_id != "start")
            .values(available_at=datetime.now(UTC) - timedelta(seconds=1), state={"race": True})
        )
        await session.execute(
            update(Execution).where(Execution.id == execution_id).values(status="cancelled")
        )
        await session.commit()

    async def claimer(name: str) -> list[uuid.UUID]:
        got: list[uuid.UUID] = []
        for _ in range(10):
            async with container.db.session() as session:
                rows = await StepRepository(session).claim(name, 3)
                rows = [r for r in rows if r.execution_id == execution_id]
                await session.commit()
            got.extend(r.id for r in rows)
        return got

    results = await asyncio.gather(*(claimer(f"racer-{i}") for i in range(12)))
    claimed = [step_id for batch in results for step_id in batch]
    assert len(claimed) == len(set(claimed))
    async with container.db.session() as session:
        rows = (
            (
                await session.execute(
                    select(ExecutionStep.locked_by).where(
                        ExecutionStep.execution_id == execution_id, ExecutionStep.node_id != "start"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert all(name and name.startswith(("racer-", "it-worker")) for name in rows)


async def test_only_one_scheduler_leads_at_a_time(container: Container) -> None:
    key = f"wfe:test:leader:{uuid.uuid4().hex}"
    first = LeaderElection(container.redis, "a", ttl_s=3, key=key)
    second = LeaderElection(container.redis, "b", ttl_s=3, key=key)
    assert await first.ensure() is True
    assert await second.ensure() is False
    assert await first.ensure() is True  # renewal
    await first.release()
    assert await second.ensure() is True
    assert await second.current() == "b"
    await container.redis.delete(key)
    assert await second.ensure() is True  # reacquired after the key vanished
    await second.release()
