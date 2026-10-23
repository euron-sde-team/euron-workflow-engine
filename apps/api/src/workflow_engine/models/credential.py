from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from workflow_engine.db.base import Base, IdMixin, TimestampMixin


class Credential(IdMixin, TimestampMixin, Base):
    """A secret, envelope-encrypted. Only metadata and non-secret fields ever leave the API."""

    __tablename__ = "credentials"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text, default="")
    public_fields: Mapped[dict[str, Any]] = mapped_column(default=dict)
    secret_fields: Mapped[list[str]] = mapped_column(default=list)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary)
    key_provider: Mapped[str] = mapped_column(String(8))
    key_ref: Mapped[str] = mapped_column(String(256))
    # Bumped on every change, so caches keyed by (id, version) never serve a stale secret.
    version: Mapped[int] = mapped_column(default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    last_used_at: Mapped[datetime | None]
