"""The engine end to end: real worker, real scheduler, real Postgres, Redis and Floci."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests.integration.conftest import Account, wait_for
from tests.integration.helpers import (
    base,
    create_workflow,
    edge,
    node,
    publish,
    run,
    step_detail,
    steps_by_node,
)

pytestmark = pytest.mark.usefixtures("worker")


async def test_a_linear_workflow_runs_to_completion(
    client: httpx.AsyncClient, owner: Account
) -> None:
    nodes = [
        node(
            "start",
            "trigger.manual",
            {
                "sample_payload": {
                    "order": {
                        "id": "SO-1042",
                        "total": 640,
                        "items": [{"sku": "TENT-2P", "qty": 2}],
                    }
                }
            },
        ),
        node(
            "shape",
            "core.transform",
            {"expression": "{id: trigger.order.id, big: trigger.order.total > `500`}"},
        ),
        node("remember", "core.set", {"assignments": [{"name": "region", "value": "west"}]}),
        node(
            "summary",
            "core.transform",
            {
                "mode": "template",
                "template": {
                    "text": "{{ steps.shape.id }} ({{ vars.region }})",
                    "big": "{{ input.big }}",
                },
            },
        ),
    ]
    edges = [edge("start", "shape"), edge("shape", "remember"), edge("remember", "summary")]
    workflow = await create_workflow(client, owner, "Linear", nodes, edges)
    started = await run(client, owner, workflow["id"], draft=True)
    execution = await wait_for(client, owner, started["execution_id"])
    assert execution["status"] == "succeeded", execution
    assert execution["mode"] == "test"
    assert execution["output"] == {"text": "SO-1042 (west)", "big": True}
    assert execution["variables"] == {"region": "west"}
    grouped = steps_by_node(execution)
    assert [s["status"] for s in execution["steps"]] == ["succeeded"] * 4
    shape = await step_detail(client, owner, execution["id"], grouped["shape"][0]["id"])
    assert shape["input"]["order"]["id"] == "SO-1042"
    assert shape["output"] == {"id": "SO-1042", "big": True}
    ran = await client.get(
        f"{base(owner)}/executions/{execution['id']}/definition", headers=owner.headers
    )
    assert ran.status_code == 200, ran.text
    assert ran.json()["version_number"] is None
    assert [n["id"] for n in ran.json()["definition"]["nodes"]] == [
        "start",
        "shape",
        "remember",
        "summary",
    ]


async def test_branches_skip_and_merges_wait_for_what_ran(
    client: httpx.AsyncClient, owner: Account
) -> None:
    nodes = [
        node("start", "trigger.manual"),
        node(
            "check",
            "flow.if",
            {"conditions": [{"left": "{{ input.total }}", "operator": "gt", "right": "500"}]},
        ),
        node("vip", "core.transform", {"mode": "template", "template": {"lane": "priority"}}),
        node("standard", "core.transform", {"mode": "template", "template": {"lane": "standard"}}),
        node("join", "flow.merge", {"mode": "merge_objects"}),
        node("done", "core.transform", {"expression": "input"}),
    ]
    edges = [
        edge("start", "check"),
        edge("check", "vip", "true"),
        edge("check", "standard", "false"),
        edge("vip", "join"),
        edge("standard", "join"),
        edge("join", "done"),
    ]
    workflow = await create_workflow(client, owner, "Branching", nodes, edges)
    await publish(client, owner, workflow["id"])
    big = await wait_for(
        client, owner, (await run(client, owner, workflow["id"], {"total": 900}))["execution_id"]
    )
    small = await wait_for(
        client, owner, (await run(client, owner, workflow["id"], {"total": 40}))["execution_id"]
    )
    assert big["output"] == {"lane": "priority"}
    assert small["output"] == {"lane": "standard"}
    statuses = {n: [s["status"] for s in steps] for n, steps in steps_by_node(small).items()}
    assert statuses["vip"] == ["skipped"]
    assert statuses["join"] == ["succeeded"]
    assert big["mode"] == "manual"


async def test_loops_call_an_api_per_batch(
    client: httpx.AsyncClient, owner: Account, demo_apis: str
) -> None:
    nodes = [
        node("start", "trigger.manual"),
        node(
            "orders",
            "http.request",
            {"url": f"{demo_apis}/shop/orders", "query": [{"name": "limit", "value": "5"}]},
        ),
        node("each", "flow.loop", {"items": "input.body.orders", "batch_size": 2}),
        node(
            "ship",
            "http.request",
            {
                "method": "POST",
                "url": f"{demo_apis}/echo",
                "body_type": "json",
                "body": {"ids": "{{ input.batch[*].id }}"},
            },
        ),
        node(
            "count",
            "core.transform",
            {"expression": "{batches: input.batches, items: input.items}"},
        ),
    ]
    edges = [
        edge("start", "orders"),
        edge("orders", "each"),
        edge("each", "ship", "batch"),
        edge("ship", "each", target_port="loop"),
        edge("each", "count", "done"),
    ]
    workflow = await create_workflow(client, owner, "Looping", nodes, edges)
    execution = await wait_for(
        client, owner, (await run(client, owner, workflow["id"], draft=True))["execution_id"]
    )
    assert execution["status"] == "succeeded", execution
    assert execution["output"] == {"batches": 3, "items": 5}
    ship = steps_by_node(execution)["ship"]
    assert [s["scope"] for s in ship] == ["/each:0", "/each:1", "/each:2"]
    detail = await step_detail(client, owner, execution["id"], ship[2]["id"])
    assert detail["input"]["batch"][0]["id"] == "SO-1005"


async def test_idempotency_keys_return_the_same_execution(
    client: httpx.AsyncClient, owner: Account
) -> None:
    workflow = await create_workflow(
        client, owner, "Idempotent", [node("start", "trigger.manual")], []
    )
    first = await run(client, owner, workflow["id"], {"n": 1}, draft=True, key="order-77")
    second = await run(client, owner, workflow["id"], {"n": 2}, draft=True, key="order-77")
    assert second["execution_id"] == first["execution_id"]
    assert second["duplicate"] is True


async def test_executions_are_listed_newest_first_with_filters(
    client: httpx.AsyncClient, owner: Account
) -> None:
    workflow = await create_workflow(client, owner, "Listed", [node("start", "trigger.manual")], [])
    ids = [(await run(client, owner, workflow["id"], draft=True))["execution_id"] for _ in range(3)]
    for execution_id in ids:
        await wait_for(client, owner, execution_id)
    page = (
        await client.get(
            f"{base(owner)}/executions?workflow_id={workflow['id']}&limit=2", headers=owner.headers
        )
    ).json()
    assert [e["id"] for e in page["items"]] == ids[::-1][:2]
    rest = (
        await client.get(
            f"{base(owner)}/executions?workflow_id={workflow['id']}&limit=2&cursor={page['next_cursor']}",
            headers=owner.headers,
        )
    ).json()
    assert [e["id"] for e in rest["items"]] == [ids[0]]
    failed = (
        await client.get(
            f"{base(owner)}/executions?status=failed&workflow_id={workflow['id']}",
            headers=owner.headers,
        )
    ).json()
    assert failed["items"] == []


async def test_a_workflow_with_only_a_trigger_finishes_at_once(
    client: httpx.AsyncClient, owner: Account
) -> None:
    workflow = await create_workflow(
        client, owner, "Just a trigger", [node("start", "trigger.manual")], []
    )
    execution = await wait_for(
        client,
        owner,
        (await run(client, owner, workflow["id"], {"hello": "world"}, draft=True))["execution_id"],
    )
    assert execution["status"] == "succeeded"
    assert execution["output"] == {"hello": "world"}


async def test_node_test_runs_return_output_without_storing_anything(
    client: httpx.AsyncClient, owner: Account, demo_apis: str
) -> None:
    response = await client.post(
        f"{base(owner)}/nodes/test",
        json={
            "node": {
                "type": "http.request",
                "config": {"url": f"{demo_apis}/crm/companies/{{{{ input.domain }}}}"},
            },
            "input": {"domain": "summitworks.example.com"},
        },
        headers=owner.headers,
    )
    body: dict[str, Any] = response.json()
    assert response.status_code == 200, body
    assert body["status"] == "succeeded"
    assert body["output"]["body"]["segment"] == "enterprise"
    assert "-> 200" in body["logs"][0]["message"]
    emitted = await client.post(
        f"{base(owner)}/nodes/test",
        json={
            "node": {
                "type": "event.emit",
                "config": {"event": "lead.qualified", "payload": "{{ input }}"},
            },
            "input": {"id": 7},
        },
        headers=owner.headers,
    )
    assert emitted.json()["events"] == [{"event": "lead.qualified", "payload": {"id": 7}}]
    failing = await client.post(
        f"{base(owner)}/nodes/test",
        json={
            "node": {"type": "core.transform", "config": {"expression": "upper(input)"}},
            "input": {"a": 1},
        },
        headers=owner.headers,
    )
    assert failing.json()["status"] == "failed"
    assert failing.json()["error"]["code"] == "expression_error"
