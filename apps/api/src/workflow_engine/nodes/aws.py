"""S3 and SQS nodes, using the deployment's own AWS identity.

Because they act with the deployment's identity, they may only touch the buckets and queues
the operator listed (`WORKFLOW_DATA_BUCKET`, `S3_ALLOWED_BUCKETS`, `SQS_ALLOWED_QUEUES`).
Without that rule any editor could read the engine's own buckets.
"""

from __future__ import annotations

from typing import Any, Literal

import anyio
import orjson
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import Field

from workflow_engine.core.config import Settings
from workflow_engine.engine.definition import RetryPolicy
from workflow_engine.nodes.base import (
    NodeConfig,
    NodeContext,
    NodeError,
    NodeResult,
    NodeType,
    templated,
)
from workflow_engine.nodes.http import KeyValue

_RETRYABLE = {
    "Throttling",
    "ThrottlingException",
    "SlowDown",
    "RequestTimeout",
    "ServiceUnavailable",
    "InternalError",
    "RequestThrottled",
}


def _aws_error(action: str, exc: Exception) -> NodeError:
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "ClientError")
        message = exc.response.get("Error", {}).get("Message", "")
        if code in {"NoSuchKey", "404", "NotFound"}:
            return NodeError("not_found", f"{action}: the object does not exist.")
        return NodeError(
            f"aws_{code}".lower()[:48],
            f"{action} failed ({code}): {message}",
            retryable=code in _RETRYABLE,
        )
    return NodeError("aws_unavailable", f"{action} failed: {exc}", retryable=True)


def allowed_buckets(settings: Settings) -> set[str]:
    buckets = set(settings.s3_allowed_buckets)
    if settings.workflow_data_bucket:
        buckets.add(settings.workflow_data_bucket)
    return buckets


def _bucket(ctx: NodeContext, requested: str | None) -> str:
    settings = ctx.services.settings
    bucket = requested or settings.workflow_data_bucket
    if not bucket:
        raise NodeError("no_bucket", "Name a bucket; this deployment has no default data bucket.")
    if bucket not in allowed_buckets(settings):
        raise NodeError(
            "bucket_not_allowed",
            f"Workflows may not use the bucket '{bucket}'. An operator can allow it with "
            "S3_ALLOWED_BUCKETS.",
        )
    return bucket


def _key(key: str) -> str:
    cleaned = key.strip()
    if not cleaned or cleaned.startswith("/") or ".." in cleaned.split("/"):
        raise NodeError("invalid_key", f"'{key}' is not a valid object key.")
    return cleaned


class S3PutConfig(NodeConfig):
    bucket: str | None = templated(
        None, max_length=63, description="Empty: the workflow data bucket."
    )
    key: str = templated(..., min_length=1, max_length=1024)
    content: Any = templated(..., widget="json")
    content_type: str = Field(default="auto", max_length=120)


async def s3_put(ctx: NodeContext, config: S3PutConfig) -> NodeResult:
    bucket, key = _bucket(ctx, config.bucket), _key(config.key)
    if isinstance(config.content, str):
        body = config.content.encode()
        content_type = "text/plain; charset=utf-8"
    else:
        body = orjson.dumps(config.content, option=orjson.OPT_INDENT_2)
        content_type = "application/json"
    if config.content_type != "auto":
        content_type = config.content_type
    s3 = ctx.services.aws.s3()
    try:
        response = await anyio.to_thread.run_sync(
            lambda: s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)
        )
    except (ClientError, BotoCoreError) as exc:
        raise _aws_error(f"Writing s3://{bucket}/{key}", exc) from exc
    ctx.log("info", f"Wrote {len(body)} bytes to s3://{bucket}/{key}")
    return NodeResult(
        output={
            "bucket": bucket,
            "key": key,
            "etag": str(response.get("ETag", "")).strip('"'),
            "size": len(body),
            "content_type": content_type,
        }
    )


class S3GetConfig(NodeConfig):
    bucket: str | None = templated(None, max_length=63)
    key: str = templated(..., min_length=1, max_length=1024)
    parse: Literal["auto", "json", "text"] = "auto"
    max_kb: int = Field(default=1024, ge=1, le=10_240)


async def s3_get(ctx: NodeContext, config: S3GetConfig) -> NodeResult:
    bucket, key = _bucket(ctx, config.bucket), _key(config.key)
    s3 = ctx.services.aws.s3()
    limit = config.max_kb * 1024

    def read() -> tuple[bytes, str, str]:
        response = s3.get_object(Bucket=bucket, Key=key)
        if int(response.get("ContentLength", 0)) > limit:
            raise NodeError("object_too_large", f"The object is larger than {config.max_kb} KB.")
        data = response["Body"].read(limit + 1)
        modified = response.get("LastModified")
        return data, str(response.get("ContentType", "")), modified.isoformat() if modified else ""

    try:
        data, content_type, last_modified = await anyio.to_thread.run_sync(read)
    except (ClientError, BotoCoreError) as exc:
        raise _aws_error(f"Reading s3://{bucket}/{key}", exc) from exc
    if len(data) > limit:
        raise NodeError("object_too_large", f"The object is larger than {config.max_kb} KB.")
    body: Any = data.decode("utf-8", errors="replace")
    if config.parse == "json" or (config.parse == "auto" and "json" in content_type):
        try:
            body = orjson.loads(data)
        except orjson.JSONDecodeError as exc:
            if config.parse == "json":
                raise NodeError("invalid_json", "The object is not valid JSON.") from exc
    ctx.log("info", f"Read {len(data)} bytes from s3://{bucket}/{key}")
    return NodeResult(
        output={
            "bucket": bucket,
            "key": key,
            "content_type": content_type,
            "size": len(data),
            "last_modified": last_modified,
            "body": body,
        }
    )


class SqsPublishConfig(NodeConfig):
    queue: str = templated(..., min_length=1, max_length=400, description="Queue name or URL.")
    message: Any = templated(..., widget="json")
    delay_s: int = Field(default=0, ge=0, le=900)
    group_id: str | None = templated(None, max_length=128, description="FIFO queues only.")
    deduplication_id: str | None = templated(None, max_length=128, description="FIFO queues only.")
    attributes: list[KeyValue] = templated(default_factory=list, widget="key-value", max_length=10)


def _queue_name(queue: str) -> str:
    return queue.rstrip("/").rsplit("/", 1)[-1]


async def sqs_publish(ctx: NodeContext, config: SqsPublishConfig) -> NodeResult:
    settings = ctx.services.settings
    name = _queue_name(config.queue)
    allowed = {_queue_name(q) for q in settings.sqs_allowed_queues}
    if name not in allowed:
        raise NodeError(
            "queue_not_allowed",
            f"Workflows may not publish to '{name}'. An operator can allow it with "
            "SQS_ALLOWED_QUEUES.",
        )
    sqs = ctx.services.aws.sqs()
    body = (
        config.message if isinstance(config.message, str) else orjson.dumps(config.message).decode()
    )

    def send() -> tuple[str, dict[str, Any]]:
        url = (
            config.queue
            if config.queue.startswith("http")
            else sqs.get_queue_url(QueueName=name)["QueueUrl"]
        )
        request: dict[str, Any] = {"QueueUrl": url, "MessageBody": body}
        if name.endswith(".fifo"):
            if not config.group_id:
                raise NodeError("group_id_required", "A FIFO queue needs a message group id.")
            request["MessageGroupId"] = config.group_id
            if config.deduplication_id:
                request["MessageDeduplicationId"] = config.deduplication_id
        elif config.delay_s:
            request["DelaySeconds"] = config.delay_s
        if config.attributes:
            request["MessageAttributes"] = {
                a.name: {"DataType": "String", "StringValue": str(a.value)}
                for a in config.attributes
            }
        return url, dict(sqs.send_message(**request))

    try:
        url, response = await anyio.to_thread.run_sync(send)
    except (ClientError, BotoCoreError) as exc:
        raise _aws_error(f"Publishing to {name}", exc) from exc
    ctx.log("info", f"Published {len(body)} bytes to {name}", message_id=response.get("MessageId"))
    return NodeResult(
        output={"message_id": response.get("MessageId", ""), "queue": name, "queue_url": url}
    )


_AWS_RETRY = RetryPolicy(max_attempts=3, initial_delay_ms=1000, max_delay_ms=20_000)

NODES = [
    NodeType(
        type="aws.s3_put",
        name="S3: put object",
        category="integration",
        description="Write JSON or text to an S3 object.",
        icon="upload",
        config_model=S3PutConfig,
        run=s3_put,
        default_retry=_AWS_RETRY,
        side_effects=True,
        sample_output={
            "bucket": "",
            "key": "",
            "etag": "",
            "size": 0,
            "content_type": "application/json",
        },
    ),
    NodeType(
        type="aws.s3_get",
        name="S3: get object",
        category="integration",
        description="Read an S3 object, parsed as JSON when it is JSON.",
        icon="download",
        config_model=S3GetConfig,
        run=s3_get,
        default_retry=_AWS_RETRY,
        sample_output={"bucket": "", "key": "", "content_type": "", "size": 0, "body": {}},
    ),
    NodeType(
        type="aws.sqs_publish",
        name="SQS: publish",
        category="integration",
        description="Send a message to an SQS queue (standard or FIFO).",
        icon="list-start",
        config_model=SqsPublishConfig,
        run=sqs_publish,
        default_retry=_AWS_RETRY,
        side_effects=True,
        sample_output={"message_id": "", "queue": "", "queue_url": ""},
    ),
]
