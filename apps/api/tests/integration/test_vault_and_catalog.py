"""Credentials (KMS envelope encryption on the emulator), variables and the catalog."""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import select, update

from tests.integration.conftest import Account
from tests.integration.helpers import base, create_workflow, credential, edge, node
from workflow_engine.models import Credential
from workflow_engine.nodes.base import NodeError
from workflow_engine.services.container import Container
from workflow_engine.services.vault import CredentialResolver


async def test_secrets_are_encrypted_and_never_returned(
    client: httpx.AsyncClient, owner: Account, container: Container
) -> None:
    created = await client.post(
        f"{base(owner)}/credentials",
        json={
            "name": "Warehouse",
            "type": "postgres",
            "data": {
                "host": "warehouse",
                "database": "shop",
                "user": "reader",
                "password": "s3cret-warehouse-pw",
            },
        },
        headers=owner.headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["public_fields"] == {
        "host": "warehouse",
        "port": 5432,
        "database": "shop",
        "user": "reader",
        "ssl_mode": "prefer",
    }
    assert body["secret_fields"] == ["password"]
    assert body["key_provider"] == "kms"
    assert "s3cret" not in created.text
    listed = await client.get(f"{base(owner)}/credentials", headers=owner.headers)
    assert "s3cret" not in listed.text

    async with container.db.session() as session:
        row = (
            await session.execute(select(Credential).where(Credential.id == uuid.UUID(body["id"])))
        ).scalar_one()
        assert b"s3cret" not in row.ciphertext
        assert row.key_ref.startswith("arn:aws:kms:")
    resolved = await CredentialResolver(container).resolve(
        uuid.UUID(body["id"]).__class__(row.workspace_id.hex), row.id, frozenset({"postgres"})
    )
    assert resolved.values["password"] == "s3cret-warehouse-pw"


async def test_a_credential_moved_to_another_workspace_cannot_be_decrypted(
    client: httpx.AsyncClient, owner: Account, stranger: Account, container: Container
) -> None:
    credential_id = uuid.UUID(
        await credential(client, owner, "Movable", "http_bearer", token="tok_move_123456")
    )
    other = (
        await client.get(f"/api/v1/workspaces/{stranger.workspace}", headers=stranger.headers)
    ).json()["id"]
    async with container.db.session() as session:
        await session.execute(
            update(Credential)
            .where(Credential.id == credential_id)
            .values(workspace_id=uuid.UUID(other))
        )
        await session.commit()
    with pytest.raises(NodeError) as error:
        await CredentialResolver(container).resolve(
            uuid.UUID(other), credential_id, frozenset({"http_bearer"})
        )
    assert error.value.code == "vault_unavailable"


async def test_updates_keep_omitted_secrets_and_bump_the_version(
    client: httpx.AsyncClient, owner: Account, container: Container
) -> None:
    credential_id = await credential(
        client, owner, "Basic", "http_basic", username="svc", password="first-password"
    )
    renamed = await client.patch(
        f"{base(owner)}/credentials/{credential_id}",
        json={"data": {"username": "svc-2"}},
        headers=owner.headers,
    )
    assert renamed.status_code == 200
    assert renamed.json()["version"] == 2
    assert renamed.json()["public_fields"] == {"username": "svc-2"}
    resolved = await CredentialResolver(container).resolve(
        uuid.UUID((await client.get(f"{base(owner)}", headers=owner.headers)).json()["id"]),
        uuid.UUID(credential_id),
        frozenset({"http_basic"}),
    )
    assert resolved.values == {"username": "svc-2", "password": "first-password"}
    invalid = await client.post(
        f"{base(owner)}/credentials",
        json={"name": "Bad", "type": "postgres", "data": {"host": "x"}},
        headers=owner.headers,
    )
    assert invalid.status_code == 422
    unknown = await client.post(
        f"{base(owner)}/credentials",
        json={"name": "Odd", "type": "ftp", "data": {}},
        headers=owner.headers,
    )
    assert unknown.status_code == 422


async def test_credentials_in_use_cannot_be_deleted(
    client: httpx.AsyncClient, owner: Account
) -> None:
    hook = await credential(
        client,
        owner,
        "Ops channel",
        "slack_webhook",
        url="https://hooks.example.com/services/T/B/x",
    )
    workflow = await create_workflow(
        client,
        owner,
        "Alerts",
        [
            node("start", "trigger.manual"),
            node("say", "slack.message", {"credential_id": hook, "text": "hi"}),
        ],
        [edge("start", "say")],
    )
    refused = await client.delete(f"{base(owner)}/credentials/{hook}", headers=owner.headers)
    assert refused.status_code == 409
    assert refused.json()["error"]["details"] == {"workflows": ["Alerts"]}
    detail = (await client.get(f"{base(owner)}/credentials/{hook}", headers=owner.headers)).json()
    assert detail["used_by"] == ["Alerts"]
    await client.delete(f"{base(owner)}/workflows/{workflow['id']}", headers=owner.headers)
    assert (
        await client.delete(f"{base(owner)}/credentials/{hook}", headers=owner.headers)
    ).status_code == 204


async def test_variables(client: httpx.AsyncClient, owner: Account) -> None:
    saved = await client.put(
        f"{base(owner)}/variables/SHOP_API",
        json={"value": "http://demo-apis:9131/shop", "description": "Demo shop"},
        headers=owner.headers,
    )
    assert saved.status_code == 200
    await client.put(
        f"{base(owner)}/variables/SHOP_API",
        json={"value": "http://shop.example.com"},
        headers=owner.headers,
    )
    listed = (await client.get(f"{base(owner)}/variables", headers=owner.headers)).json()
    assert [(v["key"], v["value"]) for v in listed] == [("SHOP_API", "http://shop.example.com")]
    assert (
        await client.put(
            f"{base(owner)}/variables/lower_case", json={"value": "x"}, headers=owner.headers
        )
    ).status_code == 422
    assert (
        await client.delete(f"{base(owner)}/variables/SHOP_API", headers=owner.headers)
    ).status_code == 204
    assert (
        await client.delete(f"{base(owner)}/variables/SHOP_API", headers=owner.headers)
    ).status_code == 404


async def test_catalog_endpoints(client: httpx.AsyncClient, owner: Account) -> None:
    types = (await client.get("/api/v1/node-types", headers=owner.headers)).json()
    by_type = {t["type"]: t for t in types}
    assert len(types) == 21
    assert by_type["http.request"]["credential_fields"] == {
        "credential_id": ["http_basic", "http_bearer", "http_header", "http_query"]
    }
    assert by_type["flow.loop"]["inputs"] == ["main", "loop"]
    assert by_type["http.request"]["config_schema"]["properties"]["url"]["x-template"] is True
    creds = (await client.get("/api/v1/credential-types", headers=owner.headers)).json()
    assert {c["type"] for c in creds} >= {"postgres", "webhook_secret", "slack_webhook"}
    preview = (
        await client.post(
            "/api/v1/tools/cron-preview",
            json={"expression": "*/15 9-17 * * 1-5", "timezone": "Europe/London"},
            headers=owner.headers,
        )
    ).json()
    assert preview["valid"] is True
    assert len(preview["next"]) == 5
    invalid = (
        await client.post(
            "/api/v1/tools/cron-preview", json={"expression": "61 * * * *"}, headers=owner.headers
        )
    ).json()
    assert invalid == {
        "valid": False,
        "description": None,
        "next": [],
        "error": "minute: 61 is outside 0-59",
    }
    assert (await client.get("/api/v1/node-types")).status_code == 401
