from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String, desc
from sqlalchemy.orm import Mapped, mapped_column

from workflow_engine.db.base import Base, CreatedMixin, IdMixin


class Event(IdMixin, CreatedMixin, Base):
    """A message on a workspace's event bus, and how many executions it started."""

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_workspace_created", "workspace_id", desc("created_at"), desc("id")),
        Index("ix_events_workspace_name", "workspace_id", "name", desc("created_at")),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    payload: Mapped[Any | None] = mapped_column(default=dict)
    source: Mapped[str] = mapped_column(String(16))
    # No foreign key: the execution may be pruned before the event, and the event stays.
    source_execution_id: Mapped[uuid.UUID | None]
    depth: Mapped[int] = mapped_column(default=0)
    matched: Mapped[int] = mapped_column(default=0)
