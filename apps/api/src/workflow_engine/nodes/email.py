"""`email.send`: send an email through SES (relayed to Mailpit by the local emulator)."""

from __future__ import annotations

import re
from typing import Any

import anyio
from botocore.exceptions import BotoCoreError, ClientError
from email_validator import EmailNotValidError, validate_email

from workflow_engine.engine.definition import RetryPolicy
from workflow_engine.nodes.base import (
    NodeConfig,
    NodeContext,
    NodeError,
    NodeResult,
    NodeType,
    templated,
)

MAX_RECIPIENTS = 50
_SPLIT = re.compile(r"[,;\s]+")
_THROTTLED = {
    "Throttling",
    "ThrottlingException",
    "TooManyRequestsException",
    "LimitExceededException",
}


class EmailConfig(NodeConfig):
    to: Any = templated(..., description="Addresses, comma separated, or a list.")
    cc: Any = templated(None)
    reply_to: str | None = templated(None, max_length=320)
    subject: str = templated(..., min_length=1, max_length=300)
    text: str = templated(..., widget="textarea", min_length=1, max_length=100_000)
    html: str | None = templated(None, widget="textarea", max_length=200_000)


def recipients(value: Any, field: str) -> list[str]:
    if value is None or value == "":
        return []
    raw = value if isinstance(value, list) else _SPLIT.split(str(value))
    addresses: list[str] = []
    for item in raw:
        text = str(item).strip()
        if not text:
            continue
        try:
            normalized = validate_email(text, check_deliverability=False).normalized
        except EmailNotValidError as exc:
            raise NodeError(
                "invalid_recipient", f"{field}: '{text}' is not an email address."
            ) from exc
        if normalized not in addresses:
            addresses.append(normalized)
    if len(addresses) > MAX_RECIPIENTS:
        raise NodeError("too_many_recipients", f"{field}: at most {MAX_RECIPIENTS} addresses.")
    return addresses


async def send(ctx: NodeContext, config: EmailConfig) -> NodeResult:
    to = recipients(config.to, "to")
    if not to:
        raise NodeError("no_recipients", "There is nobody to send the email to.")
    cc = recipients(config.cc, "cc")
    settings = ctx.services.settings
    body: dict[str, Any] = {"Text": {"Data": config.text, "Charset": "UTF-8"}}
    if config.html:
        body["Html"] = {"Data": config.html, "Charset": "UTF-8"}
    request: dict[str, Any] = {
        "FromEmailAddress": settings.mail_from,
        "Destination": {"ToAddresses": to, "CcAddresses": cc},
        "Content": {
            "Simple": {"Subject": {"Data": config.subject, "Charset": "UTF-8"}, "Body": body}
        },
    }
    if config.reply_to:
        request["ReplyToAddresses"] = recipients(config.reply_to, "reply_to")
    if settings.ses_configuration_set:
        request["ConfigurationSetName"] = settings.ses_configuration_set
    ses = ctx.services.aws.ses()
    try:
        response = await anyio.to_thread.run_sync(lambda: ses.send_email(**request))
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "ClientError")
        raise NodeError(
            "email_rejected" if code not in _THROTTLED else "email_throttled",
            f"SES refused the email ({code}): {exc.response.get('Error', {}).get('Message', '')}",
            retryable=code in _THROTTLED,
        ) from exc
    except BotoCoreError as exc:
        raise NodeError(
            "email_unavailable", f"SES is not reachable: {exc}", retryable=True
        ) from exc
    message_id = response.get("MessageId", "")
    ctx.log("info", f"Sent '{config.subject}' to {', '.join(to)}", message_id=message_id)
    return NodeResult(output={"message_id": message_id, "to": to, "cc": cc})


NODES = [
    NodeType(
        type="email.send",
        name="Send email",
        category="integration",
        description="Send an email through Amazon SES.",
        icon="mail",
        config_model=EmailConfig,
        run=send,
        default_retry=RetryPolicy(max_attempts=3, initial_delay_ms=2000, max_delay_ms=60_000),
        default_timeout_s=30,
        side_effects=True,
        sample_output={"message_id": "", "to": ["ops@example.com"], "cc": []},
    )
]
