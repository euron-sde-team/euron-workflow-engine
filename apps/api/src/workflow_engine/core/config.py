"""Runtime configuration, validated once at boot.

Every setting comes from the environment. `get_settings()` is cached, so the whole process
shares one frozen `Settings`. In production, `production_problems()` refuses development
defaults and reports every problem at once instead of one per restart.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Shipped so `uvicorn` starts with zero configuration on a laptop. Production refuses it.
DEV_SECRET = "dev-only-insecure-secret-do-not-use-in-production"  # noqa: S105

AppEnv = Literal["development", "test", "production"]
CsvList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    app_env: AppEnv = "development"
    product_name: str = "Euron WorkflowEngine"
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    log_format: Literal["json", "console"] = "json"

    # HTTP
    cors_origins: CsvList = Field(
        default_factory=lambda: ["http://localhost:3130", "http://127.0.0.1:3130"]
    )
    web_url: str = "http://localhost:3130"
    api_url: str = "http://localhost:8130"
    # Base URL printed for webhook triggers. Behind a load balancer this is the public
    # origin, which differs from API_URL when the API is only reachable internally.
    public_hooks_url: str | None = None

    # Postgres: the system of record and the work queue
    database_url: str = "postgresql+asyncpg://wfe:wfe@localhost:5453/wfe"
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_max_overflow: int = Field(default=10, ge=0, le=100)
    database_echo: bool = False
    migrate_on_boot: bool = False

    # Redis (Valkey): leader lock, wake-ups, rate limits, caches. Never the source of truth.
    redis_url: str = "redis://localhost:6413/0"

    # Sessions and API keys
    session_secret: SecretStr = SecretStr(DEV_SECRET)
    session_ttl_hours: int = Field(default=168, ge=1, le=2160)
    api_key_pepper: SecretStr = SecretStr(DEV_SECRET)
    cookie_secure: bool = False
    cookie_domain: str | None = None
    allow_signup: bool = False

    # AWS (or the Floci emulator when AWS_ENDPOINT_URL is set)
    aws_region: str = "us-east-1"
    aws_endpoint_url: str | None = None

    # Credentials vault: KMS envelope encryption in every real deployment
    vault_provider: Literal["kms", "local"] = "local"
    kms_key_id: str | None = None
    vault_local_key: SecretStr = SecretStr(DEV_SECRET)

    # Email (SES v2)
    mail_from: str = "Euron WorkflowEngine <automations@wfe.example.test>"
    ses_configuration_set: str | None = None

    # What the S3 and SQS nodes may touch with the deployment's own AWS identity
    workflow_data_bucket: str | None = None
    s3_allowed_buckets: CsvList = Field(default_factory=list)
    sqs_allowed_queues: CsvList = Field(default_factory=list)

    # Outbound network policy for the HTTP, Slack and Postgres nodes
    outbound_allow_private_networks: bool = False
    outbound_allowed_hosts: CsvList = Field(default_factory=list)
    http_user_agent: str = (
        "EuronWorkflowEngine/0.1 (+https://github.com/euron-sde-team/euron-workflow-engine)"
    )

    # Workers and the scheduler
    worker_concurrency: int = Field(default=8, ge=1, le=256)
    worker_poll_interval_ms: int = Field(default=1000, ge=50, le=60_000)
    worker_metrics_port: int = Field(default=0, ge=0, le=65535)
    step_heartbeat_s: int = Field(default=10, ge=1, le=300)
    step_stale_s: int = Field(default=60, ge=5, le=3600)
    scheduler_enabled: bool = True
    scheduler_tick_ms: int = Field(default=1000, ge=100, le=60_000)
    leader_ttl_s: int = Field(default=15, ge=3, le=300)
    shutdown_grace_s: int = Field(default=30, ge=0, le=900)

    # Limits
    max_payload_kb: int = Field(default=1024, ge=16, le=16_384)
    webhook_max_body_kb: int = Field(default=1024, ge=1, le=16_384)
    event_max_depth: int = Field(default=5, ge=1, le=20)
    default_retention_days: int = Field(default=30, ge=1, le=3650)

    # Rate limits, requests per minute
    rate_limit_login: int = Field(default=10, ge=1)
    rate_limit_webhook: int = Field(default=600, ge=1)
    rate_limit_test_run: int = Field(default=60, ge=1)
    rate_limit_events: int = Field(default=600, ge=1)

    # Local stacks only
    demo_password: SecretStr | None = None
    demo_apis_url: str = "http://localhost:9131"

    @field_validator(
        "cors_origins",
        "s3_allowed_buckets",
        "sqs_allowed_queues",
        "outbound_allowed_hosts",
        mode="before",
    )
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def hooks_base_url(self) -> str:
        return (self.public_hooks_url or self.api_url).rstrip("/")

    @property
    def max_payload_bytes(self) -> int:
        return self.max_payload_kb * 1024

    @property
    def webhook_max_body_bytes(self) -> int:
        return self.webhook_max_body_kb * 1024

    def production_problems(self) -> list[str]:
        """Every reason this configuration is unsafe to serve real users."""
        problems: list[str] = []
        session = self.session_secret.get_secret_value()
        pepper = self.api_key_pepper.get_secret_value()
        for name, value in (("SESSION_SECRET", session), ("API_KEY_PEPPER", pepper)):
            if value == DEV_SECRET or len(value) < 32:
                problems.append(f"{name} must be a random value of at least 32 characters")
        if session == pepper:
            problems.append("SESSION_SECRET and API_KEY_PEPPER must differ")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true behind HTTPS")
        if not self.cors_origins or "*" in self.cors_origins:
            problems.append("CORS_ORIGINS must list the web app origins explicitly")
        if self.vault_provider != "kms" or not self.kms_key_id:
            problems.append("VAULT_PROVIDER=kms with KMS_KEY_ID is required")
        if self.aws_endpoint_url:
            problems.append("AWS_ENDPOINT_URL points at an emulator; unset it in production")
        if self.outbound_allow_private_networks:
            problems.append(
                "OUTBOUND_ALLOW_PRIVATE_NETWORKS lets workflows reach the internal network; "
                "list the hosts you need in OUTBOUND_ALLOWED_HOSTS instead"
            )
        return problems


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
