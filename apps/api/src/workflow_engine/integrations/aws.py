"""boto3 clients configured the same way for AWS and for the Floci emulator.

`AWS_ENDPOINT_URL` (set only for the emulator) switches S3 to path-style addressing;
everything else is identical, which is the point of running against an emulator. Clients
are created lazily, once per process, and are safe to share across the worker threads
that `anyio.to_thread` runs them on.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

import boto3
from botocore.config import Config

from workflow_engine.core.config import Settings

if TYPE_CHECKING:
    from mypy_boto3_kms import KMSClient
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_sesv2 import SESV2Client
    from mypy_boto3_sqs import SQSClient


class AwsClients:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._clients: dict[str, Any] = {}
        self._lock = threading.Lock()

    def _config(self) -> Config:
        return Config(
            region_name=self._settings.aws_region,
            retries={"max_attempts": 4, "mode": "standard"},
            connect_timeout=5,
            read_timeout=30,
            s3={"addressing_style": "path" if self._settings.aws_endpoint_url else "auto"},
        )

    def _client(self, service: str) -> Any:
        client = self._clients.get(service)
        if client is None:
            with self._lock:
                client = self._clients.get(service)
                if client is None:
                    client = boto3.client(
                        service,  # type: ignore[call-overload]
                        endpoint_url=self._settings.aws_endpoint_url or None,
                        config=self._config(),
                    )
                    self._clients[service] = client
        return client

    def s3(self) -> S3Client:
        client: S3Client = self._client("s3")
        return client

    def sqs(self) -> SQSClient:
        client: SQSClient = self._client("sqs")
        return client

    def ses(self) -> SESV2Client:
        client: SESV2Client = self._client("sesv2")
        return client

    def kms(self) -> KMSClient:
        client: KMSClient = self._client("kms")
        return client

    def secrets(self) -> Any:
        """Secrets Manager, used only to read the RDS-managed database password."""
        return self._client("secretsmanager")
