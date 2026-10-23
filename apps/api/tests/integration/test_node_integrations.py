"""Nodes against real services: SES relayed to Mailpit, S3 and SQS on Floci, Postgres."""

from __future__ import annotations

import asyncio
import uuid

import boto3
import httpx
import pytest
from botocore.config import Config

from tests.integration.conftest import AWS_URL, BUCKET, QUEUE, Account, mailpit_messages, wait_for
from tests.integration.helpers import create_workflow, credential, edge, node, run, steps_by_node

pytestmark = pytest.mark.usefixtures("worker")


async def test_email_is_sent_through_ses_and_lands_in_mailpit(
    client: httpx.AsyncClient, owner: Account
) -> None:
    subject = f"Low stock {uuid.uuid4().hex[:6]}"
    nodes = [
        node("start", "trigger.manual"),
        node(
            "mail",
            "email.send",
            {
                "to": "ops@northwind.example.com",
                "subject": subject,
                "text": "Only {{ input.qty }} lanterns left.",
            },
        ),
    ]
    workflow = await create_workflow(client, owner, "Mailer", nodes, [edge("start", "mail")])
    execution = await wait_for(
        client,
        owner,
        (await run(client, owner, workflow["id"], {"qty": 3}, draft=True))["execution_id"],
    )
    assert execution["status"] == "succeeded", execution
    assert execution["output"]["to"] == ["ops@northwind.example.com"]
    for _ in range(30):
        found = [m for m in mailpit_messages() if m["Subject"] == subject]
        if found:
            break
        await asyncio.sleep(0.2)
    assert found, "the message never reached Mailpit"
    assert found[0]["To"][0]["Address"] == "ops@northwind.example.com"


async def test_s3_put_then_get_round_trips_json(client: httpx.AsyncClient, owner: Account) -> None:
    key = f"orders/{uuid.uuid4().hex}.json"
    nodes = [
        node("start", "trigger.manual"),
        node("save", "aws.s3_put", {"key": key, "content": "{{ input }}"}),
        node("load", "aws.s3_get", {"key": "{{ input.key }}"}),
    ]
    workflow = await create_workflow(
        client, owner, "Archive", nodes, [edge("start", "save"), edge("save", "load")]
    )
    execution = await wait_for(
        client,
        owner,
        (await run(client, owner, workflow["id"], {"id": "SO-9", "total": 12.5}, draft=True))[
            "execution_id"
        ],
    )
    assert execution["status"] == "succeeded", execution
    assert execution["output"]["bucket"] == BUCKET
    assert execution["output"]["body"] == {"id": "SO-9", "total": 12.5}


async def test_sqs_publish_delivers_a_message(client: httpx.AsyncClient, owner: Account) -> None:
    marker = uuid.uuid4().hex
    nodes = [
        node("start", "trigger.manual"),
        node(
            "publish",
            "aws.sqs_publish",
            {"queue": QUEUE, "message": {"marker": marker, "order": "{{ input.id }}"}},
        ),
    ]
    workflow = await create_workflow(client, owner, "Queue it", nodes, [edge("start", "publish")])
    execution = await wait_for(
        client,
        owner,
        (await run(client, owner, workflow["id"], {"id": "SO-3"}, draft=True))["execution_id"],
    )
    assert execution["status"] == "succeeded", execution
    sqs = boto3.client("sqs", endpoint_url=AWS_URL, config=Config(region_name="us-east-1"))
    url = sqs.get_queue_url(QueueName=QUEUE)["QueueUrl"]
    bodies: list[str] = []
    for _ in range(5):
        response = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10, WaitTimeSeconds=1)
        bodies.extend(m["Body"] for m in response.get("Messages", []))
        if any(marker in b for b in bodies):
            break
    assert any(f'"marker":"{marker}"' in b and '"order":"SO-3"' in b for b in bodies)
    blocked = [
        node("start", "trigger.manual"),
        node(
            "publish",
            "aws.sqs_publish",
            {"queue": "somebody-elses-queue", "message": "x"},
            retry={"max_attempts": 1},
        ),
    ]
    other = await create_workflow(
        client, owner, "Queue blocked", blocked, [edge("start", "publish")]
    )
    failed = await wait_for(
        client, owner, (await run(client, owner, other["id"], draft=True))["execution_id"]
    )
    assert failed["error"]["code"] == "queue_not_allowed"


async def test_postgres_queries_are_read_only_unless_allowed(
    client: httpx.AsyncClient, owner: Account
) -> None:
    pg = await credential(
        client,
        owner,
        "Integration database",
        "postgres",
        host="127.0.0.1",
        port=9135,
        database="wfe_it",
        user="wfe",
        password="wfe",
        ssl_mode="disable",
    )
    nodes = [
        node("start", "trigger.manual"),
        node(
            "read",
            "db.postgres_query",
            {
                "credential_id": pg,
                "sql": "SELECT slug, name FROM workspaces WHERE slug = $1",
                "parameters": ["{{ input.slug }}"],
            },
        ),
        node(
            "write",
            "db.postgres_query",
            {
                "credential_id": pg,
                "sql": "UPDATE workspaces SET description = 'x' WHERE slug = $1",
                "parameters": ["{{ input.slug }}"],
            },
        ),
    ]
    workflow = await create_workflow(
        client, owner, "Database", nodes, [edge("start", "read"), edge("read", "write")]
    )
    execution = await wait_for(
        client,
        owner,
        (await run(client, owner, workflow["id"], {"slug": owner.workspace}, draft=True))[
            "execution_id"
        ],
    )
    grouped = steps_by_node(execution)
    assert grouped["read"][0]["status"] == "succeeded"
    assert execution["status"] == "failed"
    assert execution["error"]["code"] == "read_only_violation"
