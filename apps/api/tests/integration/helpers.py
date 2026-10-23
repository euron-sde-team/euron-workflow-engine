"""Definitions and calls shared by the integration tests."""

from __future__ import annotations

from typing import Any

import httpx

from tests.integration.conftest import Account


def node(
    node_id: str, node_type: str, config: dict[str, Any] | None = None, **extra: Any
) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "name": extra.pop("name", node_id.replace("_", " ").title()),
        "config": config or {},
        **extra,
    }


def edge(
    source: str, target: str, source_port: str = "main", target_port: str = "main"
) -> dict[str, Any]:
    return {
        "id": f"{source}-{source_port}-{target}-{target_port}",
        "source": source,
        "source_port": source_port,
        "target": target,
        "target_port": target_port,
    }


def definition(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": 1, "nodes": nodes, "edges": edges}


def base(account: Account) -> str:
    return f"/api/v1/workspaces/{account.workspace}"


async def create_workflow(
    client: httpx.AsyncClient,
    account: Account,
    name: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    **settings: Any,
) -> dict[str, Any]:
    response = await client.post(
        f"{base(account)}/workflows",
        json={"name": name, "definition": definition(nodes, edges)},
        headers=account.headers,
    )
    assert response.status_code == 201, response.text
    workflow: dict[str, Any] = response.json()
    if settings:
        patched = await client.patch(
            f"{base(account)}/workflows/{workflow['id']}", json=settings, headers=account.headers
        )
        assert patched.status_code == 200, patched.text
        workflow = patched.json()
    return workflow


async def publish(
    client: httpx.AsyncClient, account: Account, workflow_id: str, *, activate: bool = True
) -> dict[str, Any]:
    response = await client.post(
        f"{base(account)}/workflows/{workflow_id}/publish",
        json={"note": "test", "activate": activate},
        headers=account.headers,
    )
    assert response.status_code == 200, response.text
    published: dict[str, Any] = response.json()
    return published


async def credential(
    client: httpx.AsyncClient, account: Account, name: str, kind: str, **data: Any
) -> str:
    response = await client.post(
        f"{base(account)}/credentials",
        json={"name": name, "type": kind, "data": data},
        headers=account.headers,
    )
    assert response.status_code == 201, response.text
    credential_id: str = response.json()["id"]
    return credential_id
