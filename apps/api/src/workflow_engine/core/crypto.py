"""Symmetric primitives: AES-256-GCM sealing, HKDF and webhook signatures.

Everything here is a thin, typed layer over `cryptography` and the standard library, so the
vault and the webhook verifier never handle nonces, tags or comparisons themselves.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

NONCE_BYTES = 12
KEY_BYTES = 32


class CryptoError(Exception):
    """Decryption failed: wrong key, wrong context, or tampered data."""


def hkdf(material: bytes, info: bytes, length: int = KEY_BYTES) -> bytes:
    """Derive a key for one purpose; `info` separates the domains (vault, signing, ...)."""
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=None, info=info).derive(material)


def new_key() -> bytes:
    return os.urandom(KEY_BYTES)


def seal(key: bytes, plaintext: bytes, aad: bytes) -> tuple[bytes, bytes]:
    """Encrypt and authenticate. Returns (nonce, ciphertext with tag)."""
    nonce = os.urandom(NONCE_BYTES)
    return nonce, AESGCM(key).encrypt(nonce, plaintext, aad)


def open_sealed(key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes:
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, aad)
    except (InvalidTag, ValueError) as exc:
        raise CryptoError("ciphertext could not be authenticated") from exc


def hmac_sha256_hex(secret: bytes, message: bytes) -> str:
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def signed_payload(body: bytes, timestamp: str | None) -> bytes:
    """What a webhook sender signs: the raw body, or `<timestamp>.<body>` when timestamped.

    Binding the timestamp into the MAC is what makes the tolerance window meaningful: an
    attacker replaying an old body cannot simply send a fresh timestamp header with it.
    """
    return body if timestamp is None else timestamp.encode() + b"." + body


def verify_signature(
    secret: str, body: bytes, provided: str, *, prefix: str = "", timestamp: str | None = None
) -> bool:
    """Constant-time check of `provided` against HMAC-SHA256(secret, signed payload).

    `provided` may carry the prefix (`sha256=...`) or not, and may list several signatures
    separated by commas, which lets a sender rotate its secret without downtime.
    """
    expected = hmac_sha256_hex(secret.encode(), signed_payload(body, timestamp))
    matched = False
    for candidate in provided.replace(" ", ",").split(","):
        value = candidate.strip()
        if prefix and value.startswith(prefix):
            value = value[len(prefix) :]
        # Keep comparing after a match so timing does not reveal which candidate matched.
        matched |= hmac.compare_digest(value.lower(), expected)
    return matched


def sign(secret: str, body: bytes, *, prefix: str = "sha256=", timestamp: str | None = None) -> str:
    """The signature a sender attaches; used by tests, the demo seed and the docs."""
    return prefix + hmac_sha256_hex(secret.encode(), signed_payload(body, timestamp))


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def random_token(nbytes: int = 24) -> str:
    return secrets.token_urlsafe(nbytes)
