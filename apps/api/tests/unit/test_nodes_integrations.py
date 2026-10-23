import httpx
import pytest
import respx
from botocore.exceptions import ClientError

from tests.unit.node_fakes import FakeAws, FakeServices, Recorder, run_node
from workflow_engine.nodes.base import NodeError

API = "https://api.example.com"


@respx.mock
async def test_http_request_with_a_bearer_credential_and_json() -> None:
    services = FakeServices()
    token = services.add_credential("http_bearer", token="sk_test_token_1234")
    route = respx.post(f"{API}/orders").mock(
        return_value=httpx.Response(201, json={"id": "SO-1"}, headers={"set-cookie": "x=1"})
    )
    config = {
        "method": "POST",
        "url": API + "/orders",
        "headers": [{"name": "X-Region", "value": "{{ input.region }}"}],
        "query": [{"name": "dry_run", "value": "false"}],
        "body_type": "json",
        "body": {"sku": "{{ input.sku }}", "qty": "{{ input.qty }}"},
        "credential_id": str(token),
    }
    result, ctx = await run_node(
        "http.request", config, {"region": "west", "sku": "TENT", "qty": 2}, services=services
    )
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer sk_test_token_1234"
    assert request.headers["x-region"] == "west"
    assert request.url.params["dry_run"] == "false"
    assert request.content == b'{"sku":"TENT","qty":2}'
    assert result.output["status"] == 201
    assert result.output["body"] == {"id": "SO-1"}
    assert "set-cookie" not in result.output["headers"]
    assert ctx.secrets == ["sk_test_token_1234"]
    assert "-> 201" in ctx.logs[0].message


@respx.mock
async def test_http_errors_are_retryable_only_for_the_listed_statuses() -> None:
    respx.get(f"{API}/flaky").mock(
        return_value=httpx.Response(503, text="busy", headers={"retry-after": "7"})
    )
    respx.get(f"{API}/missing").mock(return_value=httpx.Response(404, json={"error": "nope"}))
    with pytest.raises(NodeError) as busy:
        await run_node("http.request", {"url": f"{API}/flaky"})
    assert busy.value.code == "http_503"
    assert busy.value.retryable
    assert busy.value.retry_after_s == 7
    with pytest.raises(NodeError) as missing:
        await run_node("http.request", {"url": f"{API}/missing"})
    assert not missing.value.retryable
    assert missing.value.details["body"] == {"error": "nope"}
    result, _ = await run_node(
        "http.request", {"url": f"{API}/missing", "fail_on_http_error": False}
    )
    assert result.output["status"] == 404


@respx.mock
async def test_http_network_failures_and_limits() -> None:
    respx.get(f"{API}/slow").mock(side_effect=httpx.ReadTimeout("slow"))
    respx.get(f"{API}/down").mock(side_effect=httpx.ConnectError("refused"))
    respx.get(f"{API}/big").mock(return_value=httpx.Response(200, content=b"x" * 3000))
    with pytest.raises(NodeError) as slow:
        await run_node("http.request", {"url": f"{API}/slow"})
    assert (slow.value.code, slow.value.retryable) == ("timeout", True)
    with pytest.raises(NodeError) as down:
        await run_node("http.request", {"url": f"{API}/down"})
    assert (down.value.code, down.value.retryable) == ("network_error", True)
    with pytest.raises(NodeError) as big:
        await run_node("http.request", {"url": f"{API}/big", "max_response_kb": 1})
    assert big.value.code == "response_too_large"
    with pytest.raises(NodeError) as bad:
        await run_node("http.request", {"url": "ftp://example.com/file"})
    assert bad.value.code == "invalid_url"


@respx.mock
async def test_http_basic_header_and_query_credentials() -> None:
    services = FakeServices()
    basic = services.add_credential("http_basic", username="svc", password="hunter2-pass")
    header = services.add_credential(
        "http_header", header_name="X-Api-Key", header_value="key-123456"
    )
    query = services.add_credential("http_query", param_name="api_key", param_value="q-123456")
    route = respx.get(f"{API}/me").mock(return_value=httpx.Response(200, text="ok"))
    for credential_id in (basic, header, query):
        await run_node(
            "http.request",
            {"url": f"{API}/me", "credential_id": str(credential_id)},
            services=services,
        )
    first, second, third = (call.request for call in route.calls)
    assert first.headers["authorization"].startswith("Basic ")
    assert second.headers["x-api-key"] == "key-123456"
    assert third.url.params["api_key"] == "q-123456"


@respx.mock
async def test_slack_posts_json_to_the_webhook_from_the_vault() -> None:
    services = FakeServices()
    hook = services.add_credential(
        "slack_webhook", url="https://hooks.example.com/services/T1/B2/abc"
    )
    route = respx.post("https://hooks.example.com/services/T1/B2/abc").mock(
        return_value=httpx.Response(200, text="ok")
    )
    config = {
        "credential_id": str(hook),
        "text": "Order {{ input.id }} needs review",
        "icon_emoji": ":package:",
    }
    result, _ = await run_node("slack.message", config, {"id": "SO-9"}, services=services)
    assert (
        route.calls.last.request.content
        == b'{"text":"Order SO-9 needs review","icon_emoji":":package:"}'
    )
    assert result.output == {"status": 200, "response": "ok"}
    respx.post("https://hooks.example.com/services/T1/B2/abc").mock(
        return_value=httpx.Response(429, text="slow down")
    )
    with pytest.raises(NodeError) as error:
        await run_node("slack.message", config, {"id": "SO-9"}, services=services)
    assert error.value.retryable


async def test_email_goes_through_ses() -> None:
    aws = FakeAws(ses_client=Recorder({"send_email": {"MessageId": "m-1"}}))
    services = FakeServices(aws=aws)
    config = {
        "to": "ops@example.com; {{ input.owner }}",
        "subject": "Low stock: {{ input.sku }}",
        "text": "Only {{ input.qty }} left.",
    }
    result, _ = await run_node(
        "email.send",
        config,
        {"owner": "Maya@Example.com", "sku": "LAMP", "qty": 2},
        services=services,
    )
    name, request = aws.ses_client.calls[0]
    assert name == "send_email"
    assert request["Destination"]["ToAddresses"] == ["ops@example.com", "Maya@example.com"]
    assert request["Content"]["Simple"]["Subject"]["Data"] == "Low stock: LAMP"
    assert request["FromEmailAddress"] == "Automations <automations@wfe.example.test>"
    assert result.output == {
        "message_id": "m-1",
        "to": ["ops@example.com", "Maya@example.com"],
        "cc": [],
    }


async def test_email_validation_and_throttling() -> None:
    with pytest.raises(NodeError) as invalid:
        await run_node("email.send", {"to": "not-an-address", "subject": "x", "text": "y"})
    assert invalid.value.code == "invalid_recipient"
    throttled = ClientError(
        {"Error": {"Code": "TooManyRequestsException", "Message": "slow"}}, "SendEmail"
    )
    services = FakeServices(aws=FakeAws(ses_client=Recorder({"send_email": throttled})))
    with pytest.raises(NodeError) as error:
        await run_node(
            "email.send", {"to": "a@example.com", "subject": "x", "text": "y"}, services=services
        )
    assert error.value.retryable


async def test_s3_put_and_get_stay_inside_allowed_buckets() -> None:
    aws = FakeAws(s3_client=Recorder({"put_object": {"ETag": '"abc"'}}))
    services = FakeServices(aws=aws)
    result, _ = await run_node(
        "aws.s3_put",
        {"key": "orders/{{ input.id }}.json", "content": "{{ input }}"},
        {"id": "SO-1"},
        services=services,
    )
    assert result.output["bucket"] == "wfe-data"
    assert result.output["key"] == "orders/SO-1.json"
    assert result.output["etag"] == "abc"
    assert aws.s3_client.calls[0][1]["ContentType"] == "application/json"
    with pytest.raises(NodeError) as error:
        await run_node(
            "aws.s3_put", {"bucket": "wfe-secrets", "key": "x", "content": "y"}, services=services
        )
    assert error.value.code == "bucket_not_allowed"
    with pytest.raises(NodeError) as traversal:
        await run_node("aws.s3_put", {"key": "../escape", "content": "y"}, services=services)
    assert traversal.value.code == "invalid_key"


async def test_s3_get_parses_json() -> None:
    class Body:
        def read(self, limit: int) -> bytes:
            return b'{"rows": 3}'

    aws = FakeAws(
        s3_client=Recorder(
            {"get_object": {"Body": Body(), "ContentType": "application/json", "ContentLength": 11}}
        )
    )
    result, _ = await run_node(
        "aws.s3_get", {"key": "reports/today.json"}, services=FakeServices(aws=aws)
    )
    assert result.output["body"] == {"rows": 3}
    missing = ClientError({"Error": {"Code": "NoSuchKey", "Message": "gone"}}, "GetObject")
    aws = FakeAws(s3_client=Recorder({"get_object": missing}))
    with pytest.raises(NodeError) as error:
        await run_node("aws.s3_get", {"key": "nope.json"}, services=FakeServices(aws=aws))
    assert error.value.code == "not_found"


async def test_sqs_publish_resolves_queue_names_and_checks_the_allowlist() -> None:
    aws = FakeAws(
        sqs_client=Recorder(
            {
                "get_queue_url": {"QueueUrl": "http://floci:4566/000000000000/order-events"},
                "send_message": {"MessageId": "msg-1"},
            }
        )
    )
    services = FakeServices(aws=aws)
    result, _ = await run_node(
        "aws.sqs_publish",
        {"queue": "order-events", "message": {"id": "{{ input.id }}"}, "delay_s": 5},
        {"id": "SO-1"},
        services=services,
    )
    assert result.output["message_id"] == "msg-1"
    send = aws.sqs_client.calls[-1][1]
    assert send["MessageBody"] == '{"id":"SO-1"}'
    assert send["DelaySeconds"] == 5
    with pytest.raises(NodeError) as fifo:
        await run_node(
            "aws.sqs_publish", {"queue": "invoices.fifo", "message": "x"}, services=services
        )
    assert fifo.value.code == "group_id_required"
    with pytest.raises(NodeError) as blocked:
        await run_node(
            "aws.sqs_publish", {"queue": "billing-internal", "message": "x"}, services=services
        )
    assert blocked.value.code == "queue_not_allowed"
