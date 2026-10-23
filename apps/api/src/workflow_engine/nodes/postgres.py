"""`db.postgres_query`: run SQL against a Postgres database from the vault.

Read-only by default: the statement runs inside `BEGIN READ ONLY`, so Postgres itself
refuses writes, whatever the SQL says. Values only ever travel as bind parameters ($1, $2,
...); the SQL text is never templated, which rules out injection through payloads.
"""

from __future__ import annotations

import base64
import datetime as dt
import ssl
import uuid
from decimal import Decimal
from typing import Any, Literal

import asyncpg
from pydantic import Field

from workflow_engine.integrations.http import OutboundBlockedError, is_blocked, resolve
from workflow_engine.nodes.base import (
    NodeConfig,
    NodeContext,
    NodeError,
    NodeResult,
    NodeType,
    credential,
    templated,
    widget,
)

POSTGRES_CREDENTIALS = frozenset({"postgres"})


class PostgresConfig(NodeConfig):
    credential_id: uuid.UUID = credential("postgres", required=True)
    sql: str = widget(name="sql", min_length=1, max_length=20_000)
    parameters: list[Any] = templated(
        default_factory=list,
        widget="parameters",
        max_length=50,
        description="Values for $1, $2, ... in the SQL.",
    )
    mode: Literal["read_only", "read_write"] = "read_only"
    max_rows: int = Field(default=500, ge=1, le=10_000)
    statement_timeout_s: int = Field(default=30, ge=1, le=120)


def to_json_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return value.total_seconds()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return base64.b64encode(bytes(value)).decode()
    if isinstance(value, list | tuple):
        return [to_json_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): to_json_value(v) for k, v in value.items()}
    return str(value)


def _ssl(mode: str) -> ssl.SSLContext | bool:
    if mode == "disable":
        return False
    context = ssl.create_default_context()
    if mode == "require":
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


async def query(ctx: NodeContext, config: PostgresConfig) -> NodeResult:
    resolved = await ctx.credential(config.credential_id, POSTGRES_CREDENTIALS)
    values = resolved.values
    host, port = str(values["host"]), int(values.get("port") or 5432)
    if not ctx.services.network_policy.host_allowed(host):
        try:
            addresses = await resolve(host, port)
        except Exception as exc:
            raise NodeError("network_error", f"could not resolve {host}", retryable=True) from exc
        if any(is_blocked(address) for address in addresses):
            raise NodeError(
                "blocked_address",
                str(
                    OutboundBlockedError(
                        f"{host} is a private address; an operator can allow it with "
                        "OUTBOUND_ALLOWED_HOSTS."
                    )
                ),
            )
    try:
        connection = await asyncpg.connect(
            host=host,
            port=port,
            user=str(values["user"]),
            password=str(values.get("password") or ""),
            database=str(values["database"]),
            ssl=_ssl(str(values.get("ssl_mode") or "prefer")),
            timeout=10,
            command_timeout=config.statement_timeout_s + 5,
            server_settings={
                "application_name": "wfe-workflow",
                "statement_timeout": str(config.statement_timeout_s * 1000),
            },
        )
    except (OSError, asyncpg.PostgresError, TimeoutError) as exc:
        raise NodeError(
            "connection_failed", f"Could not connect to {host}:{port}: {exc}", retryable=True
        ) from exc
    rows: list[dict[str, Any]] = []
    columns: list[str] = []
    truncated = False
    try:
        async with connection.transaction(readonly=config.mode == "read_only"):
            statement = await connection.prepare(config.sql)
            columns = [attribute.name for attribute in statement.get_attributes()]
            async for record in statement.cursor(*config.parameters, prefetch=200):
                if len(rows) == config.max_rows:
                    truncated = True
                    break
                rows.append({key: to_json_value(value) for key, value in record.items()})
            status = statement.get_statusmsg() if not columns else ""
    except asyncpg.ReadOnlySQLTransactionError as exc:
        raise NodeError(
            "read_only_violation",
            "This statement writes, but the node is read-only. Switch the mode to read and "
            "write to allow it.",
        ) from exc
    except asyncpg.QueryCanceledError as exc:
        raise NodeError(
            "statement_timeout", f"The query ran longer than {config.statement_timeout_s} s."
        ) from exc
    except (asyncpg.PostgresConnectionError, OSError) as exc:
        raise NodeError("connection_lost", f"The connection failed: {exc}", retryable=True) from exc
    except asyncpg.PostgresError as exc:
        raise NodeError("sql_error", str(exc).strip()) from exc
    finally:
        await connection.close()
    ctx.log(
        "info",
        f"{len(rows)} row(s){' (truncated)' if truncated else ''} from {host}",
        rows=len(rows),
        truncated=truncated,
    )
    return NodeResult(
        output={
            "rows": rows,
            "row_count": len(rows),
            "columns": columns,
            "truncated": truncated,
            "status": status,
        }
    )


NODES = [
    NodeType(
        type="db.postgres_query",
        name="Postgres query",
        category="integration",
        description="Run SQL with bind parameters. Read-only transactions unless you opt in.",
        icon="database",
        config_model=PostgresConfig,
        run=query,
        default_timeout_s=60,
        sample_output={"rows": [], "row_count": 0, "columns": [], "truncated": False},
    )
]
