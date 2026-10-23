"""Data-key providers for the credentials vault (envelope encryption).

Every credential is encrypted with its own 256-bit data key. The data key is wrapped by a
key-encryption key that never leaves its provider:

- `KmsKeyProvider`: AWS KMS `GenerateDataKey` / `Decrypt`, with an encryption context
  that binds the wrapped key to its workspace and credential. Production requires it.
- `LocalKeyProvider`: AES-256-GCM under a key derived (HKDF) from `VAULT_LOCAL_KEY`, with
  the same context as associated data. For tests and laptops without the emulator.

A wrapped key copied onto another credential or workspace fails to unwrap in both.
"""

from __future__ import annotations

from typing import NamedTuple, Protocol

import anyio
from botocore.exceptions import BotoCoreError, ClientError

from workflow_engine.core import metrics
from workflow_engine.core.crypto import NONCE_BYTES, CryptoError, hkdf, new_key, open_sealed, seal
from workflow_engine.integrations.aws import AwsClients

LOCAL_KEY_REF = "local:v1"


class DataKey(NamedTuple):
    plaintext: bytes
    wrapped: bytes
    key_ref: str


class KeyProviderError(Exception):
    """The provider refused or could not be reached; retryable from a step's point of view."""


class KeyProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def generate(self, context: dict[str, str]) -> DataKey: ...

    async def unwrap(self, wrapped: bytes, context: dict[str, str], key_ref: str) -> bytes: ...

    async def check(self) -> None: ...


def context_aad(context: dict[str, str]) -> bytes:
    return ";".join(f"{k}={context[k]}" for k in sorted(context)).encode()


class LocalKeyProvider:
    name = "local"

    def __init__(self, secret: str) -> None:
        self._kek = hkdf(secret.encode(), b"wfe/vault-kek/v1")

    async def generate(self, context: dict[str, str]) -> DataKey:
        plaintext = new_key()
        nonce, ciphertext = seal(self._kek, plaintext, context_aad(context))
        metrics.VAULT_OPERATIONS.labels("generate", self.name).inc()
        return DataKey(plaintext, nonce + ciphertext, LOCAL_KEY_REF)

    async def unwrap(self, wrapped: bytes, context: dict[str, str], key_ref: str) -> bytes:
        metrics.VAULT_OPERATIONS.labels("unwrap", self.name).inc()
        try:
            return open_sealed(
                self._kek, wrapped[:NONCE_BYTES], wrapped[NONCE_BYTES:], context_aad(context)
            )
        except CryptoError as exc:
            raise KeyProviderError("the data key could not be unwrapped") from exc

    async def check(self) -> None:
        return None


class KmsKeyProvider:
    name = "kms"

    def __init__(self, aws: AwsClients, key_id: str) -> None:
        self._aws = aws
        self._key_id = key_id

    async def generate(self, context: dict[str, str]) -> DataKey:
        try:
            response = await anyio.to_thread.run_sync(
                lambda: self._aws.kms().generate_data_key(
                    KeyId=self._key_id, KeySpec="AES_256", EncryptionContext=context
                )
            )
        except (ClientError, BotoCoreError) as exc:
            raise KeyProviderError(f"KMS refused to generate a data key: {exc}") from exc
        metrics.VAULT_OPERATIONS.labels("generate", self.name).inc()
        return DataKey(response["Plaintext"], response["CiphertextBlob"], response["KeyId"])

    async def unwrap(self, wrapped: bytes, context: dict[str, str], key_ref: str) -> bytes:
        try:
            response = await anyio.to_thread.run_sync(
                lambda: self._aws.kms().decrypt(
                    CiphertextBlob=wrapped, EncryptionContext=context, KeyId=key_ref
                )
            )
        except (ClientError, BotoCoreError) as exc:
            raise KeyProviderError(f"KMS refused to unwrap the data key: {exc}") from exc
        metrics.VAULT_OPERATIONS.labels("unwrap", self.name).inc()
        return response["Plaintext"]

    async def check(self) -> None:
        try:
            await anyio.to_thread.run_sync(lambda: self._aws.kms().describe_key(KeyId=self._key_id))
        except (ClientError, BotoCoreError) as exc:
            raise KeyProviderError(f"the KMS key is not reachable: {exc}") from exc
