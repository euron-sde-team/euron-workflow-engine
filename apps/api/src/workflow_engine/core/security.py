"""Passwords, session tokens and API keys.

- Passwords: Argon2id (RFC 9106 second recommended profile, 64 MiB).
- Sessions: HS256 JWTs carrying the user's `session_version`; bumping the version (password
  change, "sign out everywhere") invalidates every outstanding token at once. A single
  logout adds the token's `jti` to a Redis denylist until it expires.
- API keys: `wfk_<prefix>_<secret>`. Only an HMAC-SHA256 of the secret, keyed with a server
  pepper, is stored, so a database leak alone cannot be replayed against the API.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from workflow_engine.core.errors import UnauthorizedError, UnprocessableError

_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)
# Verified against when an email is unknown, so a miss costs as much as a wrong password
# and response timing does not reveal which accounts exist.
_DUMMY_HASH = _hasher.hash("workflow-engine-timing-equaliser")

SESSION_ISSUER = "workflow-engine"
SESSION_AUDIENCE = "workflow-engine-web"
API_KEY_PREFIX = "wfk"
_API_KEY_PATTERN = re.compile(r"^wfk_([a-z2-7]{10})_([A-Za-z0-9_-]{43})$")
MIN_PASSWORD_LENGTH = 10


def validate_password(password: str, *, email: str | None = None) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise UnprocessableError(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > 256:
        raise UnprocessableError("Use at most 256 characters.")
    if len(set(password)) < 4:
        raise UnprocessableError("That password is too easy to guess.")
    if email and password.lower() == email.lower():
        raise UnprocessableError("Your password cannot be your email address.")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


@dataclass(frozen=True, slots=True)
class SessionClaims:
    user_id: uuid.UUID
    session_version: int
    jti: str
    expires_at: datetime


def issue_session(
    user_id: uuid.UUID, session_version: int, *, secret: str, ttl: timedelta
) -> tuple[str, SessionClaims]:
    now = datetime.now(UTC)
    claims = SessionClaims(
        user_id=user_id,
        session_version=session_version,
        jti=secrets.token_hex(16),
        expires_at=now + ttl,
    )
    token = jwt.encode(
        {
            "iss": SESSION_ISSUER,
            "aud": SESSION_AUDIENCE,
            "sub": str(user_id),
            "sv": session_version,
            "jti": claims.jti,
            "iat": int(now.timestamp()),
            "exp": int(claims.expires_at.timestamp()),
        },
        secret,
        algorithm="HS256",
    )
    return token, claims


def decode_session(token: str, *, secret: str) -> SessionClaims:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=SESSION_AUDIENCE,
            issuer=SESSION_ISSUER,
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
        return SessionClaims(
            user_id=uuid.UUID(payload["sub"]),
            session_version=int(payload.get("sv", 0)),
            jti=str(payload["jti"]),
            expires_at=datetime.fromtimestamp(payload["exp"], UTC),
        )
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise UnauthorizedError("Your session has expired. Sign in again.") from exc


@dataclass(frozen=True, slots=True)
class NewApiKey:
    plaintext: str
    prefix: str
    secret_hash: str


_BASE32 = "abcdefghijklmnopqrstuvwxyz234567"


def generate_api_key(pepper: str) -> NewApiKey:
    prefix = "".join(secrets.choice(_BASE32) for _ in range(10))
    secret = secrets.token_urlsafe(32)
    return NewApiKey(
        plaintext=f"{API_KEY_PREFIX}_{prefix}_{secret}",
        prefix=prefix,
        secret_hash=hash_api_key_secret(secret, pepper),
    )


def parse_api_key(raw: str) -> tuple[str, str] | None:
    match = _API_KEY_PATTERN.match(raw.strip())
    return (match.group(1), match.group(2)) if match else None


def hash_api_key_secret(secret: str, pepper: str) -> str:
    return hmac.new(pepper.encode(), secret.encode(), hashlib.sha256).hexdigest()


def verify_api_key_secret(secret: str, stored_hash: str, pepper: str) -> bool:
    return hmac.compare_digest(hash_api_key_secret(secret, pepper), stored_hash)
