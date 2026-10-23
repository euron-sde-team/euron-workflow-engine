"""Initial schema: people, workspaces, workflows, executions, the queue, vault, events, audit.

Revision ID: 0001
Revises:
Create Date: 2026-10-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
JSONB = pg.JSONB()


def _id() -> sa.Column:
    return sa.Column("id", UUID, nullable=False)


def _created() -> sa.Column:
    return sa.Column("created_at", TS, nullable=False, server_default=sa.func.now())


def _updated() -> sa.Column:
    return sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now())


def _fk(column: str, table: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], [f"{table}.id"], ondelete=ondelete)


def _check(name: str, column: str, values: Sequence[str]) -> sa.CheckConstraint:
    quoted = ", ".join(f"'{v}'" for v in values)
    return sa.CheckConstraint(f"{column} IN ({quoted})", name=name)


def _json_default(value: str) -> sa.TextClause:
    return sa.text(f"'{value}'::jsonb")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    op.create_table(
        "users",
        _id(),
        sa.Column("email", pg.CITEXT(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("session_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("failed_logins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", TS),
        sa.Column("last_login_at", TS),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )

    op.create_table(
        "workspaces",
        _id(),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("settings", JSONB, nullable=False, server_default=_json_default("{}")),
        sa.Column("created_by", UUID),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
        _fk("created_by", "users", "SET NULL"),
    )

    op.create_table(
        "memberships",
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        _created(),
        sa.PrimaryKeyConstraint("workspace_id", "user_id"),
        _fk("workspace_id", "workspaces", "CASCADE"),
        _fk("user_id", "users", "CASCADE"),
        _check("role", "role", ("owner", "editor", "viewer")),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    op.create_table(
        "api_keys",
        _id(),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("created_by", UUID),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("secret_hash", sa.String(64), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("last_used_at", TS),
        sa.Column("expires_at", TS),
        sa.Column("revoked_at", TS),
        _created(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prefix"),
        _fk("workspace_id", "workspaces", "CASCADE"),
        _fk("created_by", "users", "SET NULL"),
        _check("role", "role", ("editor", "viewer")),
    )
    op.create_index("ix_api_keys_workspace_id", "api_keys", ["workspace_id"])

    op.create_table(
        "audit_events",
        _id(),
        sa.Column("workspace_id", UUID),
        sa.Column("actor_user_id", UUID),
        sa.Column("actor_api_key_id", UUID),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(64)),
        sa.Column("details", JSONB, nullable=False, server_default=_json_default("{}")),
        _created(),
        sa.PrimaryKeyConstraint("id"),
        _fk("workspace_id", "workspaces", "CASCADE"),
        _fk("actor_user_id", "users", "SET NULL"),
        _fk("actor_api_key_id", "api_keys", "SET NULL"),
    )
    op.execute(
        "CREATE INDEX ix_audit_events_workspace_created "
        "ON audit_events (workspace_id, created_at DESC, id DESC)"
    )

    op.create_table(
        "workflows",
        _id(),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "tags", pg.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")
        ),
        sa.Column("draft", JSONB, nullable=False, server_default=_json_default("{}")),
        sa.Column("draft_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("draft_updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("draft_updated_by", UUID),
        sa.Column("published_version_id", UUID),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("activated_at", TS),
        sa.Column("concurrency_limit", sa.Integer()),
        sa.Column("timeout_s", sa.Integer(), nullable=False, server_default="3600"),
        sa.Column("template_slug", sa.String(64)),
        sa.Column("created_by", UUID),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name"),
        _fk("workspace_id", "workspaces", "CASCADE"),
        _fk("draft_updated_by", "users", "SET NULL"),
        _fk("created_by", "users", "SET NULL"),
        sa.CheckConstraint(
            "concurrency_limit IS NULL OR concurrency_limit BETWEEN 1 AND 1000",
            name="concurrency_limit",
        ),
        sa.CheckConstraint("timeout_s BETWEEN 10 AND 604800", name="timeout_s"),
    )
    op.execute("CREATE INDEX ix_workflows_tags ON workflows USING gin (tags)")

    op.create_table(
        "workflow_versions",
        _id(),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("workflow_id", UUID, nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("number", sa.Integer()),
        sa.Column("definition", JSONB, nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", UUID),
        _created(),
        sa.PrimaryKeyConstraint("id"),
        _fk("workspace_id", "workspaces", "CASCADE"),
        _fk("workflow_id", "workflows", "CASCADE"),
        _fk("created_by", "users", "SET NULL"),
        _check("kind", "kind", ("published", "snapshot")),
        sa.CheckConstraint("(kind = 'published') = (number IS NOT NULL)", name="number"),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_workflow_versions_number "
        "ON workflow_versions (workflow_id, number) WHERE number IS NOT NULL"
    )
    op.create_index(
        "ix_workflow_versions_checksum", "workflow_versions", ["workflow_id", "checksum"]
    )
    op.create_foreign_key(
        "fk_workflows_published_version_id_workflow_versions",
        "workflows",
        "workflow_versions",
        ["published_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "workflow_triggers",
        _id(),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("workflow_id", UUID, nullable=False),
        sa.Column("version_id", UUID, nullable=False),
        sa.Column("node_id", sa.String(48), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("webhook_path", sa.String(120)),
        sa.Column("webhook_method", sa.String(8)),
        sa.Column("event_name", sa.String(120)),
        sa.Column("cron_expression", sa.String(120)),
        sa.Column("timezone", sa.String(64)),
        sa.Column("interval_s", sa.Integer()),
        sa.Column("config", JSONB, nullable=False, server_default=_json_default("{}")),
        sa.Column("next_fire_at", TS),
        sa.Column("last_fired_at", TS),
        _created(),
        sa.PrimaryKeyConstraint("id"),
        _fk("workspace_id", "workspaces", "CASCADE"),
        _fk("workflow_id", "workflows", "CASCADE"),
        _fk("version_id", "workflow_versions", "CASCADE"),
        _check("kind", "kind", ("webhook", "cron", "interval", "event")),
    )
    op.create_index("ix_workflow_triggers_workflow_id", "workflow_triggers", ["workflow_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_workflow_triggers_webhook_path "
        "ON workflow_triggers (workspace_id, webhook_path) WHERE kind = 'webhook'"
    )
    op.execute(
        "CREATE INDEX ix_workflow_triggers_event_name "
        "ON workflow_triggers (workspace_id, event_name) WHERE kind = 'event'"
    )
    op.execute(
        "CREATE INDEX ix_workflow_triggers_due "
        "ON workflow_triggers (next_fire_at) WHERE kind IN ('cron', 'interval')"
    )

    op.create_table(
        "variables",
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_by", UUID),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("workspace_id", "key"),
        _fk("workspace_id", "workspaces", "CASCADE"),
        _fk("updated_by", "users", "SET NULL"),
        sa.CheckConstraint("key ~ '^[A-Z][A-Z0-9_]{0,63}$'", name="key"),
    )

    op.create_table(
        "credentials",
        _id(),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("public_fields", JSONB, nullable=False, server_default=_json_default("{}")),
        sa.Column(
            "secret_fields",
            pg.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("wrapped_key", sa.LargeBinary(), nullable=False),
        sa.Column("key_provider", sa.String(8), nullable=False),
        sa.Column("key_ref", sa.String(256), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", UUID),
        sa.Column("last_used_at", TS),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name"),
        _fk("workspace_id", "workspaces", "CASCADE"),
        _fk("created_by", "users", "SET NULL"),
        _check("key_provider", "key_provider", ("kms", "local")),
    )

    op.create_table(
        "events",
        _id(),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("payload", JSONB),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("source_execution_id", UUID),
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matched", sa.Integer(), nullable=False, server_default="0"),
        _created(),
        sa.PrimaryKeyConstraint("id"),
        _fk("workspace_id", "workspaces", "CASCADE"),
        _check("source", "source", ("api", "workflow", "system")),
    )
    op.execute(
        "CREATE INDEX ix_events_workspace_created ON events (workspace_id, created_at DESC, id DESC)"
    )
    op.execute(
        "CREATE INDEX ix_events_workspace_name ON events (workspace_id, name, created_at DESC)"
    )

    op.create_table(
        "executions",
        _id(),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("workflow_id", UUID, nullable=False),
        sa.Column("version_id", UUID, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("trigger_kind", sa.String(16), nullable=False),
        sa.Column("trigger_node_id", sa.String(48), nullable=False),
        sa.Column("trigger_payload", JSONB),
        sa.Column("idempotency_key", sa.String(200)),
        sa.Column("event_id", UUID),
        sa.Column("event_depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_of_id", UUID),
        sa.Column("resume_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state", JSONB, nullable=False, server_default=_json_default("{}")),
        sa.Column("output", JSONB),
        sa.Column("error", JSONB),
        sa.Column("created_by_user_id", UUID),
        sa.Column("created_by_api_key_id", UUID),
        sa.Column("started_at", TS),
        sa.Column("finished_at", TS),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("deadline_at", TS),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint("id"),
        _fk("workspace_id", "workspaces", "CASCADE"),
        _fk("workflow_id", "workflows", "CASCADE"),
        _fk("version_id", "workflow_versions", "CASCADE"),
        _fk("event_id", "events", "SET NULL"),
        _fk("retry_of_id", "executions", "SET NULL"),
        _fk("created_by_user_id", "users", "SET NULL"),
        _fk("created_by_api_key_id", "api_keys", "SET NULL"),
        _check(
            "status", "status", ("queued", "running", "waiting", "succeeded", "failed", "cancelled")
        ),
        _check("mode", "mode", ("production", "manual", "test")),
        _check(
            "trigger_kind",
            "trigger_kind",
            ("manual", "webhook", "cron", "interval", "event", "retry"),
        ),
    )
    op.execute(
        "CREATE INDEX ix_executions_workspace_created "
        "ON executions (workspace_id, created_at DESC, id DESC)"
    )
    op.execute(
        "CREATE INDEX ix_executions_workflow_created ON executions (workflow_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX ix_executions_queued ON executions (workflow_id, created_at) "
        "WHERE status = 'queued'"
    )
    op.execute(
        "CREATE INDEX ix_executions_running ON executions (workflow_id) WHERE status = 'running'"
    )
    op.execute(
        "CREATE INDEX ix_executions_deadline ON executions (deadline_at) "
        "WHERE status IN ('running', 'waiting')"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_executions_idempotency_key "
        "ON executions (workflow_id, idempotency_key) WHERE idempotency_key IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_executions_finished ON executions (finished_at) "
        "WHERE finished_at IS NOT NULL"
    )

    op.create_table(
        "execution_steps",
        _id(),
        sa.Column("execution_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("node_id", sa.String(48), nullable=False),
        sa.Column("node_type", sa.String(64), nullable=False),
        sa.Column("node_name", sa.String(80), nullable=False),
        sa.Column("run_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scope", sa.String(400), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("input", JSONB),
        sa.Column("output", JSONB),
        sa.Column(
            "ports", pg.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")
        ),
        sa.Column("error", JSONB),
        sa.Column("state", JSONB, nullable=False, server_default=_json_default("{}")),
        sa.Column("available_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("locked_by", sa.String(120)),
        sa.Column("locked_at", TS),
        sa.Column("heartbeat_at", TS),
        sa.Column("timeout_s", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("started_at", TS),
        sa.Column("finished_at", TS),
        sa.Column("duration_ms", sa.Integer()),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint("id"),
        _fk("execution_id", "executions", "CASCADE"),
        _fk("workspace_id", "workspaces", "CASCADE"),
        _check(
            "status",
            "status",
            ("queued", "running", "waiting", "succeeded", "failed", "skipped", "cancelled"),
        ),
    )
    # The claim query: stays an index scan however much history the table holds.
    op.execute(
        "CREATE INDEX ix_execution_steps_claim ON execution_steps (available_at, id) "
        "WHERE status = 'queued'"
    )
    op.execute(
        "CREATE INDEX ix_execution_steps_stale ON execution_steps (heartbeat_at) "
        "WHERE status = 'running'"
    )
    op.execute(
        "CREATE INDEX ix_execution_steps_waiting ON execution_steps (available_at) "
        "WHERE status = 'waiting'"
    )
    op.execute(
        "CREATE INDEX ix_execution_steps_execution ON execution_steps (execution_id, created_at)"
    )

    op.create_table(
        "execution_logs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("execution_id", UUID, nullable=False),
        sa.Column("step_id", UUID),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("level", sa.String(8), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data", JSONB, nullable=False, server_default=_json_default("{}")),
        _created(),
        sa.PrimaryKeyConstraint("id"),
        _fk("execution_id", "executions", "CASCADE"),
        _fk("step_id", "execution_steps", "CASCADE"),
        _fk("workspace_id", "workspaces", "CASCADE"),
        _check("level", "level", ("debug", "info", "warn", "error")),
    )
    op.create_index("ix_execution_logs_execution", "execution_logs", ["execution_id", "id"])

    op.create_table(
        "dead_letters",
        _id(),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("workflow_id", UUID, nullable=False),
        sa.Column("execution_id", UUID, nullable=False),
        sa.Column("step_id", UUID),
        sa.Column("node_id", sa.String(48), nullable=False),
        sa.Column("node_name", sa.String(80), nullable=False),
        sa.Column("error", JSONB, nullable=False, server_default=_json_default("{}")),
        sa.Column("input", JSONB),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("resolved_at", TS),
        sa.Column("resolved_by", UUID),
        _created(),
        sa.PrimaryKeyConstraint("id"),
        _fk("workspace_id", "workspaces", "CASCADE"),
        _fk("workflow_id", "workflows", "CASCADE"),
        _fk("execution_id", "executions", "CASCADE"),
        _fk("step_id", "execution_steps", "SET NULL"),
        _fk("resolved_by", "users", "SET NULL"),
        _check("status", "status", ("open", "retried", "discarded")),
    )
    op.execute(
        "CREATE INDEX ix_dead_letters_workspace_status "
        "ON dead_letters (workspace_id, status, created_at DESC)"
    )
    op.create_index("ix_dead_letters_execution", "dead_letters", ["execution_id"])

    # The audit log is append-only. DELETE is allowed only as a cascade from deleting the
    # workspace (the RI trigger runs at depth 1, so this trigger sees depth 2).
    op.execute(
        """
        CREATE FUNCTION audit_events_append_only() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'audit_events is append-only (% refused)', TG_OP
            USING ERRCODE = 'insufficient_privilege';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION audit_events_append_only()"
    )
    # A version that ran must stay exactly what ran.
    op.execute(
        """
        CREATE FUNCTION workflow_versions_immutable() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'workflow versions are immutable'
            USING ERRCODE = 'insufficient_privilege';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER workflow_versions_immutable BEFORE UPDATE ON workflow_versions "
        "FOR EACH ROW EXECUTE FUNCTION workflow_versions_immutable()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS workflow_versions_immutable ON workflow_versions")
    op.execute("DROP FUNCTION IF EXISTS workflow_versions_immutable()")
    op.execute("DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS audit_events_append_only()")
    for table in (
        "dead_letters",
        "execution_logs",
        "execution_steps",
        "executions",
        "events",
        "credentials",
        "variables",
        "workflow_triggers",
    ):
        op.drop_table(table)
    op.drop_constraint(
        "fk_workflows_published_version_id_workflow_versions", "workflows", type_="foreignkey"
    )
    for table in ("workflow_versions", "workflows", "audit_events", "api_keys", "memberships"):
        op.drop_table(table)
    op.drop_table("workspaces")
    op.drop_table("users")
