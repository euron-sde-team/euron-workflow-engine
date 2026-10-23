"""Accounts, sessions, workspaces, members, API keys and the audit log over HTTP."""

from __future__ import annotations

import re
import uuid

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.integration.conftest import PASSWORD, Account, signup
from workflow_engine.services.container import Container


async def test_probes_and_system_info(client: httpx.AsyncClient) -> None:
    assert (await client.get("/livez")).json() == {"status": "ok"}
    ready = await client.get("/readyz")
    assert ready.status_code == 200, ready.text
    assert ready.json()["checks"] == {"database": "ok", "redis": "ok", "vault": "ok"}
    info = (await client.get("/api/v1/system/info")).json()
    assert info["vault_provider"] == "kms"
    assert info["hooks_base_url"] == "http://localhost:8130"
    metrics = await client.get("/metrics")
    assert "wfe_http_requests_total" in metrics.text


async def test_sign_in_sign_out_and_wrong_passwords(
    client: httpx.AsyncClient, owner: Account
) -> None:
    bad = await client.post(
        "/api/v1/auth/login", json={"email": owner.email, "password": "wrong-password-1"}
    )
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "invalid_credentials"
    good = await client.post(
        "/api/v1/auth/login", json={"email": owner.email, "password": PASSWORD}
    )
    assert good.status_code == 200
    token = good.json()["token"]
    headers = {"authorization": f"Bearer {token}"}
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 200
    assert (await client.post("/api/v1/auth/logout", headers=headers)).status_code == 204
    after = await client.get("/api/v1/auth/me", headers=headers)
    assert after.status_code == 401


async def test_cookie_sessions_refuse_cross_site_writes(
    client: httpx.AsyncClient, owner: Account
) -> None:
    login = await client.post(
        "/api/v1/auth/login", json={"email": owner.email, "password": PASSWORD}
    )
    assert "wfe_session" in login.cookies
    response = await client.post(
        "/api/v1/workspaces",
        json={"name": "Phishing"},
        headers={"origin": "https://evil.example.com"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf"
    client.cookies.clear()


async def test_non_members_cannot_see_a_workspace(
    client: httpx.AsyncClient, owner: Account, stranger: Account
) -> None:
    for path in ("", "/members", "/audit", "/api-keys"):
        response = await client.get(
            f"/api/v1/workspaces/{owner.workspace}{path}", headers=stranger.headers
        )
        assert response.status_code == 404, path
        assert response.json()["error"]["code"] == "not_found"


async def test_every_workspace_route_answers_404_to_non_members(
    client: httpx.AsyncClient, app: FastAPI, owner: Account, stranger: Account
) -> None:
    """A sweep over the whole API: a non-member learns nothing and changes nothing."""
    prefix = "/api/v1/workspaces/{workspace}"
    checked = []
    # The OpenAPI document lists every route with its methods, however routers are mounted.
    for template, operations in app.openapi()["paths"].items():
        if not template.startswith(prefix):
            continue
        path = template.replace("{workspace}", owner.workspace)
        path = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)
        for method in sorted(m.upper() for m in operations):
            body = {} if method in {"POST", "PUT", "PATCH"} else None
            response = await client.request(method, path, json=body, headers=stranger.headers)
            assert response.status_code == 404, (method, template, response.text)
            assert response.json()["error"]["code"] == "not_found"
            checked.append(f"{method} {template}")
    assert len(checked) >= 50, checked
    # The owner's workspace is untouched.
    me = await client.get(f"/api/v1/workspaces/{owner.workspace}", headers=owner.headers)
    assert me.status_code == 200


async def test_roles_gate_membership_changes(client: httpx.AsyncClient, owner: Account) -> None:
    editor = await signup(client, "Ravi Editor")
    added = await client.post(
        f"/api/v1/workspaces/{owner.workspace}/members",
        json={"email": editor.email, "role": "editor"},
        headers=owner.headers,
    )
    assert added.status_code == 201
    assert added.json()["temporary_password"] is None
    new_person = await client.post(
        f"/api/v1/workspaces/{owner.workspace}/members",
        json={"email": "new.hire@northwind.example.com", "role": "viewer"},
        headers=owner.headers,
    )
    assert new_person.json()["temporary_password"]
    forbidden = await client.post(
        f"/api/v1/workspaces/{owner.workspace}/members",
        json={"email": "someone@northwind.example.com"},
        headers=editor.headers,
    )
    assert forbidden.status_code == 403
    last_owner = await client.patch(
        f"/api/v1/workspaces/{owner.workspace}/members/{owner.user_id}",
        json={"role": "viewer"},
        headers=owner.headers,
    )
    assert last_owner.status_code == 422
    assert last_owner.json()["error"]["code"] == "last_owner"


async def test_api_keys_are_shown_once_scoped_and_revocable(
    client: httpx.AsyncClient, owner: Account, stranger: Account
) -> None:
    created = await client.post(
        f"/api/v1/workspaces/{owner.workspace}/api-keys",
        json={"name": "CI", "role": "editor"},
        headers=owner.headers,
    )
    assert created.status_code == 201
    key = created.json()["key"]
    assert key.startswith("wfk_")
    listed = (
        await client.get(f"/api/v1/workspaces/{owner.workspace}/api-keys", headers=owner.headers)
    ).json()
    assert "key" not in listed[0]
    keyed = {"authorization": f"Bearer {key}"}
    assert (
        await client.get(f"/api/v1/workspaces/{owner.workspace}", headers=keyed)
    ).status_code == 200
    assert (
        await client.get(f"/api/v1/workspaces/{stranger.workspace}", headers=keyed)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/workspaces/{owner.workspace}/api-keys", headers=keyed)
    ).status_code == 403
    revoked = await client.delete(
        f"/api/v1/workspaces/{owner.workspace}/api-keys/{created.json()['id']}",
        headers=owner.headers,
    )
    assert revoked.status_code == 204
    after = await client.get(f"/api/v1/workspaces/{owner.workspace}", headers=keyed)
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "invalid_api_key"


async def test_the_audit_log_pages_and_refuses_edits(
    client: httpx.AsyncClient, owner: Account, container: Container
) -> None:
    for name in ("one", "two", "three"):
        await client.post(
            f"/api/v1/workspaces/{owner.workspace}/api-keys",
            json={"name": name},
            headers=owner.headers,
        )
    first = (
        await client.get(
            f"/api/v1/workspaces/{owner.workspace}/audit?limit=2", headers=owner.headers
        )
    ).json()
    assert [e["action"] for e in first["items"]] == ["api_key.created", "api_key.created"]
    assert first["items"][0]["actor_type"] == "user"
    second = (
        await client.get(
            f"/api/v1/workspaces/{owner.workspace}/audit?limit=10&cursor={first['next_cursor']}",
            headers=owner.headers,
        )
    ).json()
    assert [e["action"] for e in second["items"]] == ["api_key.created", "workspace.created"]
    assert second["next_cursor"] is None
    bad_cursor = await client.get(
        f"/api/v1/workspaces/{owner.workspace}/audit?cursor=nonsense", headers=owner.headers
    )
    assert bad_cursor.status_code == 422

    async with container.db.session() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(text("UPDATE audit_events SET action = 'x'"))
        await session.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(text("DELETE FROM audit_events"))
        await session.rollback()

    # Deleting the workspace cascades through the guard.
    deleted = await client.delete(f"/api/v1/workspaces/{owner.workspace}", headers=owner.headers)
    assert deleted.status_code == 204
