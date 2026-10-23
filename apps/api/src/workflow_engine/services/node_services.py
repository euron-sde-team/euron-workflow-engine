"""What running nodes may use, wired to the process container."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import httpx

from workflow_engine.core.config import Settings
from workflow_engine.integrations.aws import AwsClients
from workflow_engine.integrations.http import NetworkPolicy
from workflow_engine.nodes.base import ResolvedCredential
from workflow_engine.services.container import Container
from workflow_engine.services.vault import CredentialResolver


@dataclass(frozen=True)
class RuntimeServices:
    container: Container

    @property
    def settings(self) -> Settings:
        return self.container.settings

    @property
    def http(self) -> httpx.AsyncClient:
        return self.container.http

    @property
    def aws(self) -> AwsClients:
        return self.container.aws

    @property
    def network_policy(self) -> NetworkPolicy:
        return self.container.network_policy

    async def credential(
        self, workspace_id: uuid.UUID, credential_id: uuid.UUID, accepted: frozenset[str]
    ) -> ResolvedCredential:
        return await CredentialResolver(self.container).resolve(
            workspace_id, credential_id, accepted
        )
