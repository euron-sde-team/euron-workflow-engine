"""Process-wide infrastructure, built once at startup and shared by every request and step.

Services are cheap objects created per request (or per step) around one database session;
everything expensive (connection pools, AWS clients, the HTTP client) lives here.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
from redis.asyncio import Redis

from workflow_engine.core.config import Settings
from workflow_engine.core.ratelimit import RateLimiter
from workflow_engine.db.session import Database
from workflow_engine.engine.definition import WorkflowDefinition
from workflow_engine.engine.graph import Graph
from workflow_engine.integrations.aws import AwsClients
from workflow_engine.integrations.http import NetworkPolicy, guarded_client
from workflow_engine.integrations.keys import KeyProvider, KmsKeyProvider, LocalKeyProvider
from workflow_engine.integrations.signals import Signals
from workflow_engine.nodes.base import NodeType
from workflow_engine.nodes.registry import REGISTRY


@dataclass(frozen=True, slots=True)
class CompiledDefinition:
    definition: WorkflowDefinition
    graph: Graph


class DefinitionCache:
    """Parsed definitions by version id. Versions are immutable, so entries never go stale."""

    def __init__(self, capacity: int = 512) -> None:
        self._capacity = capacity
        self._entries: OrderedDict[uuid.UUID, CompiledDefinition] = OrderedDict()

    def get(
        self, version_id: uuid.UUID, raw: dict[str, Any] | None = None
    ) -> CompiledDefinition | None:
        entry = self._entries.get(version_id)
        if entry is not None:
            self._entries.move_to_end(version_id)
            return entry
        if raw is None:
            return None
        definition = WorkflowDefinition.model_validate(raw)
        entry = CompiledDefinition(definition, Graph(definition))
        self._entries[version_id] = entry
        if len(self._entries) > self._capacity:
            self._entries.popitem(last=False)
        return entry


@dataclass
class Container:
    settings: Settings
    db: Database
    redis: Redis
    limiter: RateLimiter
    signals: Signals
    aws: AwsClients
    keys: KeyProvider
    http: httpx.AsyncClient
    network_policy: NetworkPolicy
    registry: Mapping[str, NodeType] = field(default_factory=lambda: REGISTRY)
    definitions: DefinitionCache = field(default_factory=DefinitionCache)

    async def close(self) -> None:
        await self.http.aclose()
        await self.redis.aclose()
        await self.db.dispose()


def build_key_provider(settings: Settings, aws: AwsClients) -> KeyProvider:
    if settings.vault_provider == "kms":
        if not settings.kms_key_id:
            raise ValueError("VAULT_PROVIDER=kms needs KMS_KEY_ID")
        return KmsKeyProvider(aws, settings.kms_key_id)
    return LocalKeyProvider(settings.vault_local_key.get_secret_value())


def build_container(settings: Settings, *, application_name: str = "wfe-api") -> Container:
    redis = Redis.from_url(
        settings.redis_url, decode_responses=False, health_check_interval=30, socket_timeout=5
    )
    aws = AwsClients(settings)
    policy = NetworkPolicy.build(
        settings.outbound_allow_private_networks, settings.outbound_allowed_hosts
    )
    return Container(
        settings=settings,
        db=Database(settings, application_name=application_name),
        redis=redis,
        limiter=RateLimiter(redis),
        signals=Signals(redis),
        aws=aws,
        keys=build_key_provider(settings, aws),
        http=guarded_client(policy, user_agent=settings.http_user_agent),
        network_policy=policy,
    )
