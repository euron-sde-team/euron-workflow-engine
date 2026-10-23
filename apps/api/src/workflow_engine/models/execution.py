from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text, desc, func, text
from sqlalchemy.orm import Mapped, mapped_column

from workflow_engine.db.base import Base, CreatedMixin, IdMixin, TimestampMixin


class Execution(IdMixin, TimestampMixin, Base):
    """One run of one workflow version."""

    __tablename__ = "executions"
    __table_args__ = (
        Index("ix_executions_workspace_created", "workspace_id", desc("created_at"), desc("id")),
        Index("ix_executions_workflow_created", "workflow_id", desc("created_at")),
        Index(
            "ix_executions_queued",
            "workflow_id",
            "created_at",
            postgresql_where=text("status = 'queued'"),
        ),
        Index("ix_executions_running", "workflow_id", postgresql_where=text("status = 'running'")),
        Index(
            "ix_executions_deadline",
            "deadline_at",
            postgresql_where=text("status IN ('running', 'waiting')"),
        ),
        Index(
            "uq_executions_idempotency_key",
            "workflow_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index(
            "ix_executions_finished",
            "finished_at",
            postgresql_where=text("finished_at IS NOT NULL"),
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"))
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_versions.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(16))
    mode: Mapped[str] = mapped_column(String(16))
    trigger_kind: Mapped[str] = mapped_column(String(16))
    trigger_node_id: Mapped[str] = mapped_column(String(48))
    trigger_payload: Mapped[Any | None] = mapped_column(default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"))
    event_depth: Mapped[int] = mapped_column(default=0)
    retry_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("executions.id", ondelete="SET NULL")
    )
    resume_count: Mapped[int] = mapped_column(default=0)
    # Routing state (joins, loops, run counters) and the execution's variables.
    state: Mapped[dict[str, Any]] = mapped_column(default=dict)
    output: Mapped[Any | None]
    error: Mapped[dict[str, Any] | None]
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by_api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("api_keys.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    deadline_at: Mapped[datetime | None]


class ExecutionStep(IdMixin, TimestampMixin, Base):
    """One activation of one node. Steps are what the queue hands to workers."""

    __tablename__ = "execution_steps"
    __table_args__ = (
        # The claim query: stays an index scan however much history the table holds.
        Index(
            "ix_execution_steps_claim",
            "available_at",
            "id",
            postgresql_where=text("status = 'queued'"),
        ),
        Index(
            "ix_execution_steps_stale", "heartbeat_at", postgresql_where=text("status = 'running'")
        ),
        Index(
            "ix_execution_steps_waiting",
            "available_at",
            postgresql_where=text("status = 'waiting'"),
        ),
        Index("ix_execution_steps_execution", "execution_id", "created_at"),
    )

    execution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("executions.id", ondelete="CASCADE"))
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    node_id: Mapped[str] = mapped_column(String(48))
    node_type: Mapped[str] = mapped_column(String(64))
    node_name: Mapped[str] = mapped_column(String(80))
    run_index: Mapped[int] = mapped_column(default=0)
    scope: Mapped[str] = mapped_column(String(400), default="")
    status: Mapped[str] = mapped_column(String(16))
    attempt: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=1)
    input: Mapped[Any | None]
    output: Mapped[Any | None]
    ports: Mapped[list[str]] = mapped_column(default=list)
    error: Mapped[dict[str, Any] | None]
    state: Mapped[dict[str, Any]] = mapped_column(default=dict)
    available_at: Mapped[datetime] = mapped_column(server_default=func.now())
    locked_by: Mapped[str | None] = mapped_column(String(120))
    locked_at: Mapped[datetime | None]
    heartbeat_at: Mapped[datetime | None]
    timeout_s: Mapped[int] = mapped_column(default=30)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class ExecutionLog(CreatedMixin, Base):
    __tablename__ = "execution_logs"
    __table_args__ = (Index("ix_execution_logs_execution", "execution_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("executions.id", ondelete="CASCADE"))
    step_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("execution_steps.id", ondelete="CASCADE")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    level: Mapped[str] = mapped_column(String(8))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)


class DeadLetter(IdMixin, CreatedMixin, Base):
    """A step that exhausted its retries, parked until someone resumes or discards it."""

    __tablename__ = "dead_letters"
    __table_args__ = (
        Index("ix_dead_letters_workspace_status", "workspace_id", "status", desc("created_at")),
        Index("ix_dead_letters_execution", "execution_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"))
    execution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("executions.id", ondelete="CASCADE"))
    step_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("execution_steps.id", ondelete="SET NULL")
    )
    node_id: Mapped[str] = mapped_column(String(48))
    node_name: Mapped[str] = mapped_column(String(80))
    error: Mapped[dict[str, Any]] = mapped_column(default=dict)
    input: Mapped[Any | None]
    status: Mapped[str] = mapped_column(String(16))
    resolved_at: Mapped[datetime | None]
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
