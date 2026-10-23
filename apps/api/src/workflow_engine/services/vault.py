"""The credentials vault: envelope encryption with a fresh data key per credential.

    create:  data key = provider.generate(context)        # KMS GenerateDataKey
             ciphertext = AES-256-GCM(data key, values, aad=context)
             store ciphertext, nonce, wrapped data key; drop the plaintext key
    use:     data key = provider.unwrap(wrapped, context)  # KMS Decrypt
             values = AES-256-GCM-open(...)

The context is `{workspace_id, credential_id}`: KMS refuses to unwrap a key presented with
another context, and GCM refuses the ciphertext under other associated data, so a row
copied into another workspace or credential cannot be decrypted. Values never leave this
module except to a running node; the API returns metadata and non-secret fields only.

Python cannot zero memory reliably, so a plaintext data key lives until it is garbage
collected; it is never logged, cached or stored.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import orjson
from pydantic import ValidationError
from redis.exceptions import RedisError
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from workflow_engine.core.crypto import CryptoError, open_sealed, seal
from workflow_engine.core.errors import ConflictError, NotFoundError, UnprocessableError
from workflow_engine.core.ids import uuid7
from workflow_engine.core.logging import get_logger
from workflow_engine.integrations.keys import KeyProviderError, context_aad
from workflow_engine.models import Credential
from workflow_engine.nodes.base import NodeError, ResolvedCredential
from workflow_engine.nodes.credentials import CREDENTIAL_TYPES, CredentialType
from workflow_engine.repositories.credentials import CredentialRepository
from workflow_engine.repositories.workflows import WorkflowRepository
from workflow_engine.services import audit
from workflow_engine.services.container import Container
from workflow_engine.services.principal import Principal

log = get_logger("wfe.vault")
_TOUCH_INTERVAL_S = 60


def _context(workspace_id: uuid.UUID, credential_id: uuid.UUID) -> dict[str, str]:
    return {"workspace_id": str(workspace_id), "credential_id": str(credential_id)}


def credential_type(kind: str) -> CredentialType:
    spec = CREDENTIAL_TYPES.get(kind)
    if spec is None:
        raise UnprocessableError(
            f"Unknown credential type '{kind}'.", details={"types": sorted(CREDENTIAL_TYPES)}
        )
    return spec


def _validated(spec: CredentialType, data: dict[str, Any]) -> dict[str, Any]:
    try:
        return spec.model.model_validate(data).model_dump(mode="json")
    except ValidationError as exc:
        details = [
            {"field": ".".join(str(p) for p in e.get("loc", ())), "message": e.get("msg")}
            for e in exc.errors()
        ]
        raise UnprocessableError("Some credential fields are invalid.", details=details) from exc


class CredentialService:
    def __init__(self, container: Container, session: AsyncSession) -> None:
        self.c = container
        self.session = session
        self.credentials = CredentialRepository(session)

    async def _seal(
        self, workspace_id: uuid.UUID, credential_id: uuid.UUID, values: dict[str, Any]
    ) -> tuple[bytes, bytes, bytes, str]:
        context = _context(workspace_id, credential_id)
        try:
            key = await self.c.keys.generate(context)
        except KeyProviderError as exc:
            raise UnprocessableError(
                "The key service is unavailable; the credential was not saved.",
                code="vault_unavailable",
            ) from exc
        nonce, ciphertext = seal(key.plaintext, orjson.dumps(values), context_aad(context))
        return ciphertext, nonce, key.wrapped, key.key_ref

    async def create(
        self,
        workspace_id: uuid.UUID,
        principal: Principal,
        *,
        name: str,
        kind: str,
        description: str,
        data: dict[str, Any],
    ) -> Credential:
        spec = credential_type(kind)
        values = _validated(spec, data)
        if await self.credentials.by_name(workspace_id, name.strip()):
            raise ConflictError("A credential with that name already exists.")
        credential_id = uuid7()
        ciphertext, nonce, wrapped, key_ref = await self._seal(workspace_id, credential_id, values)
        public, _ = spec.split(values)
        credential = await self.credentials.add(
            Credential(
                id=credential_id,
                workspace_id=workspace_id,
                name=name.strip(),
                type=kind,
                description=description.strip(),
                public_fields=public,
                secret_fields=sorted(spec.secret_fields),
                ciphertext=ciphertext,
                nonce=nonce,
                wrapped_key=wrapped,
                key_provider=self.c.keys.name,
                key_ref=key_ref,
                created_by=principal.user_id,
            )
        )
        await audit.record(
            self.session,
            workspace_id=workspace_id,
            principal=principal,
            action="credential.created",
            target_type="credential",
            target_id=credential.id,
            details={"name": credential.name, "type": kind},
        )
        await self.session.commit()
        return credential

    async def get(self, workspace_id: uuid.UUID, credential_id: uuid.UUID) -> Credential:
        credential = await self.credentials.get(workspace_id, credential_id)
        if credential is None:
            raise NotFoundError("Credential not found.")
        return credential

    async def all(self, workspace_id: uuid.UUID) -> list[tuple[Credential, list[str]]]:
        rows = await self.credentials.all(workspace_id)
        workflows = WorkflowRepository(self.session)
        return [
            (row, [w.name for w in await workflows.referencing(workspace_id, str(row.id))])
            for row in rows
        ]

    async def used_by(self, workspace_id: uuid.UUID, credential_id: uuid.UUID) -> list[str]:
        workflows = await WorkflowRepository(self.session).referencing(
            workspace_id, str(credential_id)
        )
        return [w.name for w in workflows]

    async def update(
        self,
        workspace_id: uuid.UUID,
        principal: Principal,
        credential_id: uuid.UUID,
        *,
        name: str | None,
        description: str | None,
        data: dict[str, Any] | None,
    ) -> Credential:
        credential = await self.get(workspace_id, credential_id)
        changed: list[str] = []
        if name is not None and name.strip() != credential.name:
            clash = await self.credentials.by_name(workspace_id, name.strip())
            if clash and clash.id != credential.id:
                raise ConflictError("A credential with that name already exists.")
            credential.name = name.strip()
            changed.append("name")
        if description is not None and description.strip() != credential.description:
            credential.description = description.strip()
            changed.append("description")
        if data is not None:
            spec = credential_type(credential.type)
            # Omitted secret fields keep their value, so an edit form never has to show them.
            current = await self._open(credential)
            merged = {**current, **{k: v for k, v in data.items() if v not in (None, "")}}
            values = _validated(spec, merged)
            ciphertext, nonce, wrapped, key_ref = await self._seal(
                workspace_id, credential.id, values
            )
            credential.ciphertext, credential.nonce = ciphertext, nonce
            credential.wrapped_key, credential.key_ref = wrapped, key_ref
            credential.key_provider = self.c.keys.name
            credential.public_fields, _ = spec.split(values)
            credential.version += 1
            changed.extend(sorted(k for k in data if k in spec.model.model_fields))
        if changed:
            await audit.record(
                self.session,
                workspace_id=workspace_id,
                principal=principal,
                action="credential.updated",
                target_type="credential",
                target_id=credential.id,
                details={"name": credential.name, "fields": changed},
            )
            await self.session.commit()
        return credential

    async def delete(
        self, workspace_id: uuid.UUID, principal: Principal, credential_id: uuid.UUID
    ) -> None:
        credential = await self.get(workspace_id, credential_id)
        users = await self.used_by(workspace_id, credential_id)
        if users:
            raise ConflictError(
                "Workflows still use this credential.",
                code="credential_in_use",
                details={"workflows": users},
            )
        await self.session.delete(credential)
        await audit.record(
            self.session,
            workspace_id=workspace_id,
            principal=principal,
            action="credential.deleted",
            target_type="credential",
            target_id=credential_id,
            details={"name": credential.name, "type": credential.type},
        )
        await self.session.commit()

    async def _open(self, credential: Credential) -> dict[str, Any]:
        return await decrypt(self.c, credential)


async def decrypt(container: Container, credential: Credential) -> dict[str, Any]:
    if credential.key_provider != container.keys.name:
        raise KeyProviderError(
            f"encrypted with the {credential.key_provider} provider; this deployment uses "
            f"{container.keys.name}. Enter the credential again."
        )
    context = _context(credential.workspace_id, credential.id)
    data_key = await container.keys.unwrap(credential.wrapped_key, context, credential.key_ref)
    try:
        plaintext = open_sealed(
            data_key, credential.nonce, credential.ciphertext, context_aad(context)
        )
    except CryptoError as exc:
        raise KeyProviderError("the credential could not be authenticated") from exc
    values: dict[str, Any] = orjson.loads(plaintext)
    return values


class CredentialResolver:
    """Decrypts credentials for running nodes, in its own short transaction."""

    def __init__(self, container: Container) -> None:
        self.c = container

    async def resolve(
        self, workspace_id: uuid.UUID, credential_id: uuid.UUID, accepted: frozenset[str]
    ) -> ResolvedCredential:
        async with self.c.db.session() as session:
            credential = await CredentialRepository(session).get(workspace_id, credential_id)
            if credential is None:
                raise NodeError("credential_missing", "The credential this node uses was deleted.")
            if credential.type not in accepted:
                raise NodeError(
                    "credential_type",
                    f"This node cannot use a {credential.type} credential.",
                )
            try:
                values = await decrypt(self.c, credential)
            except KeyProviderError as exc:
                raise NodeError(
                    "vault_unavailable",
                    f"The credential could not be decrypted: {exc}",
                    retryable=True,
                ) from exc
            await self._touch(session, credential)
        return ResolvedCredential(credential.id, credential.type, values)

    async def _touch(self, session: AsyncSession, credential: Credential) -> None:
        try:
            fresh = await self.c.redis.set(
                f"cred:touched:{credential.id}", b"1", ex=_TOUCH_INTERVAL_S, nx=True
            )
        except RedisError:
            return
        if fresh:
            await session.execute(
                update(Credential)
                .where(Credential.id == credential.id)
                .values(last_used_at=datetime.now(UTC))
            )
            await session.commit()
