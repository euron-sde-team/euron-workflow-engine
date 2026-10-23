import pytest

from workflow_engine.core.crypto import (
    CryptoError,
    hkdf,
    new_key,
    open_sealed,
    seal,
    sign,
    verify_signature,
)

BODY = b'{"order_id":"SO-1042","total":129.5}'


def test_sealing_round_trips_and_binds_the_associated_data() -> None:
    key = new_key()
    nonce, ciphertext = seal(key, b"s3cr3t", b"ws-1|cred-1")
    assert open_sealed(key, nonce, ciphertext, b"ws-1|cred-1") == b"s3cr3t"
    with pytest.raises(CryptoError):
        open_sealed(key, nonce, ciphertext, b"ws-2|cred-1")
    with pytest.raises(CryptoError):
        open_sealed(new_key(), nonce, ciphertext, b"ws-1|cred-1")
    tampered = bytes([ciphertext[0] ^ 1]) + ciphertext[1:]
    with pytest.raises(CryptoError):
        open_sealed(key, nonce, tampered, b"ws-1|cred-1")


def test_hkdf_separates_domains() -> None:
    material = b"m" * 32
    assert hkdf(material, b"wfe/vault/v1") != hkdf(material, b"wfe/other/v1")
    assert len(hkdf(material, b"wfe/vault/v1")) == 32


def test_signatures_verify_with_or_without_prefix() -> None:
    signature = sign("whsec_demo", BODY)
    assert signature.startswith("sha256=")
    assert verify_signature("whsec_demo", BODY, signature, prefix="sha256=")
    assert verify_signature("whsec_demo", BODY, signature.removeprefix("sha256="), prefix="sha256=")
    assert not verify_signature("other", BODY, signature, prefix="sha256=")
    assert not verify_signature("whsec_demo", BODY + b" ", signature, prefix="sha256=")


def test_timestamped_signatures_bind_the_timestamp() -> None:
    signature = sign("whsec_demo", BODY, timestamp="1761206400")
    assert verify_signature("whsec_demo", BODY, signature, prefix="sha256=", timestamp="1761206400")
    assert not verify_signature(
        "whsec_demo", BODY, signature, prefix="sha256=", timestamp="1761206401"
    )


def test_any_of_several_signatures_may_match_during_rotation() -> None:
    header = f"{sign('old-secret', BODY)}, {sign('new-secret', BODY)}"
    assert verify_signature("new-secret", BODY, header, prefix="sha256=")
    assert verify_signature("old-secret", BODY, header, prefix="sha256=")
    assert not verify_signature("third", BODY, header, prefix="sha256=")
