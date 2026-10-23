import pytest

from workflow_engine.integrations.keys import (
    LOCAL_KEY_REF,
    KeyProviderError,
    LocalKeyProvider,
    context_aad,
)

CONTEXT = {"workspace": "w1", "credential": "c1"}


async def test_local_data_keys_round_trip_under_their_context() -> None:
    provider = LocalKeyProvider("local-vault-secret")
    key = await provider.generate(CONTEXT)
    assert len(key.plaintext) == 32
    assert key.key_ref == LOCAL_KEY_REF
    assert await provider.unwrap(key.wrapped, CONTEXT, key.key_ref) == key.plaintext


async def test_a_wrapped_key_moved_to_another_credential_fails() -> None:
    provider = LocalKeyProvider("local-vault-secret")
    key = await provider.generate(CONTEXT)
    with pytest.raises(KeyProviderError):
        await provider.unwrap(key.wrapped, {"workspace": "w1", "credential": "c2"}, key.key_ref)
    with pytest.raises(KeyProviderError):
        await LocalKeyProvider("another-secret").unwrap(key.wrapped, CONTEXT, key.key_ref)


def test_context_is_canonical() -> None:
    assert context_aad({"b": "2", "a": "1"}) == b"a=1;b=2"
