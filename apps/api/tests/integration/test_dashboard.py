"""The dashboard aggregates real executions."""

from __future__ import annotations

import httpx
import pytest

from tests.integration.conftest import Account, wait_for
from tests.integration.helpers import base, create_workflow, edge, node, run

pytestmark = pytest.mark.usefixtures("worker")


async def test_the_dashboard_counts_rates_and_lists_failures(
    client: httpx.AsyncClient, owner: Account
) -> None:
    good = await create_workflow(
        client,
        owner,
        "Good",
        [node("start", "trigger.manual"), node("ok", "core.transform", {"expression": "`1`"})],
        [edge("start", "ok")],
    )
    bad = await create_workflow(
        client,
        owner,
        "Bad",
        [node("start", "trigger.manual"), node("stop", "flow.stop", {"message": "nope"})],
        [edge("start", "stop")],
    )
    for workflow, count in ((good, 3), (bad, 1)):
        for _ in range(count):
            await wait_for(
                client,
                owner,
                (await run(client, owner, workflow["id"], draft=True))["execution_id"],
            )
    body = (await client.get(f"{base(owner)}/dashboard?window=24h", headers=owner.headers)).json()
    assert body["totals"] == {
        "total": 4,
        "succeeded": 3,
        "failed": 1,
        "cancelled": 0,
        "in_progress": 0,
    }
    assert body["success_rate"] == 0.75
    assert len(body["volume"]) == 24
    assert sum(b["succeeded"] for b in body["volume"]) == 3
    assert body["recent_failures"][0]["workflow_name"] == "Bad"
    assert body["recent_failures"][0]["code"] == "stopped"
    assert body["busiest"][0]["name"] == "Good"
    assert body["slowest"][0]["name"] == "Good"
    assert body["dead_letters_open"] == 1
    assert body["workflows"] == 2
    assert any(w["id"] == "it-worker-1" for w in body["workers"])
    weekly = (await client.get(f"{base(owner)}/dashboard?window=7d", headers=owner.headers)).json()
    assert len(weekly["volume"]) == 7
    assert (
        await client.get(f"{base(owner)}/dashboard?window=1y", headers=owner.headers)
    ).status_code == 422
