"""Workflows over HTTP: drafts, validation, publishing, activation, versions, portability."""

from __future__ import annotations

import httpx

from tests.integration.conftest import Account, signup
from tests.integration.helpers import base, create_workflow, credential, edge, node, publish


async def test_a_new_workflow_starts_with_a_manual_trigger(
    client: httpx.AsyncClient, owner: Account
) -> None:
    response = await client.post(
        f"{base(owner)}/workflows", json={"name": "Blank"}, headers=owner.headers
    )
    assert response.status_code == 201
    body = response.json()
    assert [n["type"] for n in body["draft"]["nodes"]] == ["trigger.manual"]
    assert body["issues"] == []
    assert body["published_version"] is None
    assert body["has_unpublished_changes"] is True
    duplicate = await client.post(
        f"{base(owner)}/workflows", json={"name": "blank"}, headers=owner.headers
    )
    assert duplicate.status_code == 409


async def test_drafts_save_with_optimistic_concurrency_and_report_issues(
    client: httpx.AsyncClient, owner: Account
) -> None:
    workflow = await create_workflow(
        client, owner, "Draft test", [node("start", "trigger.manual")], []
    )
    url = f"{base(owner)}/workflows/{workflow['id']}/draft"
    broken = {
        "schema_version": 1,
        "nodes": [
            node("start", "trigger.manual"),
            node("fetch", "http.request", {"url": "{{ input.["}),
        ],
        "edges": [edge("start", "fetch")],
    }
    saved = await client.put(
        url,
        json={"definition": broken, "revision": workflow["draft_revision"]},
        headers=owner.headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == workflow["draft_revision"] + 1
    issues = saved.json()["issues"]
    assert [(i["code"], i["node_id"], i["field"]) for i in issues] == [
        ("invalid_template", "fetch", "url")
    ]
    stale = await client.put(
        url,
        json={"definition": broken, "revision": workflow["draft_revision"]},
        headers=owner.headers,
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "stale_draft"
    malformed = await client.put(
        url,
        json={"definition": {"nodes": [{"id": "Bad Id"}]}, "revision": 2},
        headers=owner.headers,
    )
    assert malformed.status_code == 422
    assert malformed.json()["error"]["code"] == "invalid_definition"
    refused = await client.post(
        f"{base(owner)}/workflows/{workflow['id']}/publish", json={}, headers=owner.headers
    )
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "invalid_workflow"
    assert refused.json()["error"]["details"][0]["field"] == "url"


async def test_publishing_creates_versions_and_activation_indexes_triggers(
    client: httpx.AsyncClient, owner: Account
) -> None:
    nodes = [
        node(
            "every_morning",
            "trigger.cron",
            {"expression": "0 8 * * MON-FRI", "timezone": "Asia/Kolkata"},
        ),
        node("every_minute", "trigger.interval", {"every": 1, "unit": "minutes"}),
        node("note", "core.set", {"assignments": [{"name": "ran", "value": True}]}),
    ]
    edges = [edge("every_morning", "note"), edge("every_minute", "note")]
    workflow = await create_workflow(client, owner, "Scheduled", nodes, edges)
    published = await publish(client, owner, workflow["id"])
    assert published["active"] is True
    assert published["published_version"] == 1
    assert published["has_unpublished_changes"] is False
    triggers = {t["node_id"]: t for t in published["triggers"]}
    assert triggers["every_morning"]["summary"] == "Every weekdays at 08:00 (Asia/Kolkata)"
    assert triggers["every_morning"]["next_fire_at"] is not None
    assert published["next_run_at"] is not None
    again = await publish(client, owner, workflow["id"])
    assert again["published_version"] == 1  # unchanged draft: no new version

    versions = (
        await client.get(
            f"{base(owner)}/workflows/{workflow['id']}/versions", headers=owner.headers
        )
    ).json()
    assert [(v["number"], v["is_current"]) for v in versions] == [(1, True)]
    deactivated = await client.post(
        f"{base(owner)}/workflows/{workflow['id']}/deactivate", headers=owner.headers
    )
    assert deactivated.json()["active"] is False
    assert all(t["next_fire_at"] is None for t in deactivated.json()["triggers"])


async def test_webhook_paths_are_unique_among_active_workflows(
    client: httpx.AsyncClient, owner: Account
) -> None:
    hook = node("hook", "trigger.webhook", {"path": "orders", "auth": "none"})
    first = await create_workflow(
        client,
        owner,
        "Orders A",
        [hook, node("a", "core.set", {"assignments": [{"name": "x", "value": 1}]})],
        [edge("hook", "a")],
    )
    second = await create_workflow(
        client,
        owner,
        "Orders B",
        [hook, node("b", "core.set", {"assignments": [{"name": "x", "value": 1}]})],
        [edge("hook", "b")],
    )
    detail = await publish(client, owner, first["id"])
    assert detail["triggers"][0]["url"] == f"http://localhost:8130/hooks/{owner.workspace}/orders"
    clash = await client.post(
        f"{base(owner)}/workflows/{second['id']}/publish",
        json={"activate": True},
        headers=owner.headers,
    )
    assert clash.status_code == 409
    assert clash.json()["error"]["code"] == "webhook_path_taken"
    assert "Orders A" in clash.json()["error"]["message"]


async def test_restore_copies_a_version_into_the_draft(
    client: httpx.AsyncClient, owner: Account
) -> None:
    workflow = await create_workflow(
        client, owner, "Versioned", [node("start", "trigger.manual")], []
    )
    await publish(client, owner, workflow["id"], activate=False)
    detail = (
        await client.get(f"{base(owner)}/workflows/{workflow['id']}", headers=owner.headers)
    ).json()
    changed = dict(detail["draft"])
    changed["nodes"] = [
        *changed["nodes"],
        node("extra", "core.set", {"assignments": [{"name": "y", "value": 2}]}),
    ]
    changed["edges"] = [edge("start", "extra")]
    await client.put(
        f"{base(owner)}/workflows/{workflow['id']}/draft",
        json={"definition": changed, "revision": detail["draft_revision"]},
        headers=owner.headers,
    )
    await publish(client, owner, workflow["id"], activate=False)
    restored = await client.post(
        f"{base(owner)}/workflows/{workflow['id']}/versions/1/restore", headers=owner.headers
    )
    assert restored.status_code == 200
    assert [n["id"] for n in restored.json()["draft"]["nodes"]] == ["start"]
    assert restored.json()["published_version"] == 2
    assert restored.json()["has_unpublished_changes"] is True


async def test_export_and_import_resolve_credentials_by_name(
    client: httpx.AsyncClient, owner: Account
) -> None:
    token = await credential(
        client, owner, "Shop API token", "http_bearer", token="tok_export_123456"
    )
    nodes = [
        node("start", "trigger.manual"),
        node(
            "fetch",
            "http.request",
            {"url": "https://shop.example.com/orders", "credential_id": token},
        ),
    ]
    workflow = await create_workflow(client, owner, "Portable", nodes, [edge("start", "fetch")])
    exported = await client.get(
        f"{base(owner)}/workflows/{workflow['id']}/export", headers=owner.headers
    )
    assert exported.status_code == 200
    assert 'filename="portable.json"' in exported.headers["content-disposition"]
    document = exported.json()
    assert document["credentials"] == [{"name": "Shop API token", "type": "http_bearer"}]
    assert (
        document["definition"]["nodes"][1]["config"]["credential_id"]
        == "@credential:Shop API token"
    )
    assert "tok_export" not in exported.text

    elsewhere = await signup(client, "Lena Importer")
    imported = await client.post(
        f"{base(elsewhere)}/workflows/import", json=document, headers=elsewhere.headers
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["unresolved_credentials"] == [
        {"name": "Shop API token", "type": "http_bearer"}
    ]
    assert (
        any(
            i["code"] == "invalid_config" or i["code"] == "missing_credential"
            for i in imported.json()["workflow"]["issues"]
        )
        or imported.json()["workflow"]["draft"]["nodes"][1]["config"]["credential_id"] is None
    )

    await credential(client, elsewhere, "shop api token", "http_bearer", token="tok_other_123456")
    again = await client.post(
        f"{base(elsewhere)}/workflows/import", json=document, headers=elsewhere.headers
    )
    assert again.json()["unresolved_credentials"] == []
    assert again.json()["workflow"]["name"] == "Portable (2)"
    bad = await client.post(
        f"{base(elsewhere)}/workflows/import", json={"format": "other"}, headers=elsewhere.headers
    )
    assert bad.status_code == 422


async def test_viewers_read_but_cannot_change_workflows(
    client: httpx.AsyncClient, owner: Account
) -> None:
    viewer = await signup(client, "Vera Viewer")
    await client.post(
        f"{base(owner)}/members",
        json={"email": viewer.email, "role": "viewer"},
        headers=owner.headers,
    )
    workflow = await create_workflow(
        client, owner, "Read only", [node("start", "trigger.manual")], []
    )
    viewer_base = f"/api/v1/workspaces/{owner.workspace}"
    assert (await client.get(f"{viewer_base}/workflows", headers=viewer.headers)).status_code == 200
    assert (
        await client.get(f"{viewer_base}/workflows/{workflow['id']}", headers=viewer.headers)
    ).status_code == 200
    denied = await client.post(
        f"{viewer_base}/workflows", json={"name": "Nope"}, headers=viewer.headers
    )
    assert denied.status_code == 403
    assert (
        await client.delete(f"{viewer_base}/workflows/{workflow['id']}", headers=viewer.headers)
    ).status_code == 403


async def test_lists_page_search_and_filter(client: httpx.AsyncClient, owner: Account) -> None:
    for name, tags in (
        ("Invoice sync", ["billing"]),
        ("Invoice reminders", ["billing", "email"]),
        ("Lead routing", ["sales"]),
    ):
        created = await client.post(
            f"{base(owner)}/workflows", json={"name": name, "tags": tags}, headers=owner.headers
        )
        assert created.status_code == 201
    found = (
        await client.get(f"{base(owner)}/workflows?search=invoice&limit=1", headers=owner.headers)
    ).json()
    assert found["total"] == 2
    assert len(found["items"]) == 1
    tagged = (await client.get(f"{base(owner)}/workflows?tag=email", headers=owner.headers)).json()
    assert [w["name"] for w in tagged["items"]] == ["Invoice reminders"]
