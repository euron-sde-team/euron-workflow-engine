from __future__ import annotations

from workflow_engine.schemas.common import ApiModel


class SystemInfo(ApiModel):
    product_name: str
    version: str
    hooks_base_url: str
    allow_signup: bool
    needs_setup: bool
    vault_provider: str
    mail_from: str
    workflow_data_bucket: str | None
    sqs_allowed_queues: list[str]
    max_payload_kb: int
    webhook_max_body_kb: int
