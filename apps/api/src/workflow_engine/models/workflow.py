from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from workflow_engine.db.base import Base, CreatedMixin, IdMixin, TimestampMixin


class Workflow(IdMixin, TimestampMixin, Base):
    """A named graph with one editable draft and immutable published versions."""

    __tablename__ = "workflows"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name"),
        Index("ix_workflows_tags", "tags", postgresql_using="gin"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(default=list)
    draft: Mapped[dict[str, Any]] = mapped_column(default=dict)
    # Optimistic concurrency for the editor: a save must name the revision it started from.
    draft_revision: Mapped[int] = mapped_column(default=1)
    draft_updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
    draft_updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    published_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workflow_versions.id", ondelete="SET NULL", use_alter=True)
    )
    active: Mapped[bool] = mapped_column(default=False)
    activated_at: Mapped[datetime | None]
    concurrency_limit: Mapped[int | None] = mapped_column(Integer)
    timeout_s: Mapped[int] = mapped_column(default=3600)
    template_slug: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class WorkflowVersion(IdMixin, CreatedMixin, Base):
    """An immutable definition. Published versions are numbered; snapshots back test runs."""

    __tablename__ = "workflow_versions"
    __table_args__ = (
        Index(
            "uq_workflow_versions_number",
            "workflow_id",
            "number",
            unique=True,
            postgresql_where=text("number IS NOT NULL"),
        ),
        Index("ix_workflow_versions_checksum", "workflow_id", "checksum"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))
    number: Mapped[int | None] = mapped_column(Integer)
    definition: Mapped[dict[str, Any]]
    checksum: Mapped[str] = mapped_column(String(64))
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class WorkflowTrigger(IdMixin, CreatedMixin, Base):
    """A trigger of an active workflow's published version, indexed for fast lookup."""

    __tablename__ = "workflow_triggers"
    __table_args__ = (
        Index("ix_workflow_triggers_workflow_id", "workflow_id"),
        Index(
            "uq_workflow_triggers_webhook_path",
            "workspace_id",
            "webhook_path",
            unique=True,
            postgresql_where=text("kind = 'webhook'"),
        ),
        Index(
            "ix_workflow_triggers_event_name",
            "workspace_id",
            "event_name",
            postgresql_where=text("kind = 'event'"),
        ),
        Index(
            "ix_workflow_triggers_due",
            "next_fire_at",
            postgresql_where=text("kind IN ('cron', 'interval')"),
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"))
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_versions.id", ondelete="CASCADE")
    )
    node_id: Mapped[str] = mapped_column(String(48))
    kind: Mapped[str] = mapped_column(String(16))
    webhook_path: Mapped[str | None] = mapped_column(String(120))
    webhook_method: Mapped[str | None] = mapped_column(String(8))
    event_name: Mapped[str | None] = mapped_column(String(120))
    cron_expression: Mapped[str | None] = mapped_column(String(120))
    timezone: Mapped[str | None] = mapped_column(String(64))
    interval_s: Mapped[int | None] = mapped_column(Integer)
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    next_fire_at: Mapped[datetime | None]
    last_fired_at: Mapped[datetime | None]


class Variable(Base):
    """A non-secret workspace setting, readable in templates as `env.KEY`."""

    __tablename__ = "variables"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
