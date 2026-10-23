# WorkflowEngine API, workers and scheduler

FastAPI service for Euron WorkflowEngine, plus the worker process (step executor and
leader-elected scheduler) that runs from the same image with a different command.

```bash
uv sync                                         # Python 3.12 and every dependency
uv run uvicorn workflow_engine.main:create_app --factory --reload --port 8130
uv run wfe worker                               # executor + scheduler candidate
uv run wfe --help                               # CLI: migrations, users, demo data, openapi
uv run pytest tests/unit                        # unit tests, no services needed
../../scripts/test-deps.sh up && uv run pytest tests/integration   # Postgres, Valkey, Floci, Mailpit
```

## Layout

```text
src/workflow_engine/
|-- main.py          app factory: middleware, routers, lifespan (pools, migrations, vault check)
|-- worker.py        worker process: executor loop, scheduler candidate, metrics, graceful shutdown
|-- cli.py           typer CLI (wfe)
|-- core/            config, logging, errors, request context, security, crypto, rate limits, metrics
|-- db/              engine and sessions, declarative base, migrations runner
|-- migrations/      Alembic revisions (run programmatically, advisory-locked)
|-- models/          SQLAlchemy models, one module per aggregate
|-- schemas/         Pydantic request and response models
|-- repositories/    the only code that touches the database
|-- services/        business rules and transactions; engine.py routes executions, steps.py runs one step
|-- runtime/         long-running loops: executor, scheduler, leader election, presence
|-- engine/          pure core: definitions, graph validation, routing, expressions, templates, cron, backoff
|-- nodes/           one module per node family: config model, ports, run()
|-- integrations/    AWS clients, KMS key providers, the guarded HTTP transport, Redis signals
|-- api/             routes and dependencies (principal, workspace roles, rate limits)
|-- templates/       the templates gallery (portable workflow documents)
`-- demo/            the demo APIs and the `make demo` seed
```

## The rules

| Layer | May import | Must not |
| --- | --- | --- |
| `api/routes` | schemas, services, `api/deps`, presenters | query the database, commit, or hold business rules |
| `services` | repositories, `engine`, `nodes`, `integrations`, `core` | import FastAPI or depend on a request |
| `repositories` | models, `db` | commit, call a service, or skip the `workspace_id` filter |
| `engine` | `core` only | do I/O; it is pure and unit tested through a simulator |
| `nodes` | `engine`, `core`, the `NodeServices` protocol | reach the database or a client directly; everything goes through the services the worker passes in |
| `runtime` | services, `core` | contain business rules; it only schedules and loops |

**Workspace isolation.** Every repository method that reads workspace data takes
`workspace_id` as a required argument. The `WorkspaceAccess` dependency in `api/deps.py`
resolves the caller's role first and answers 404 to non-members, so a workspace's existence
is not revealed either.

**Transactions.** A service method that writes commits its own transaction. The engine is
the exception that proves the rule: `Engine.commit()` commits, then runs the admissions and
signals that must only happen after the commit.

**The queue.** Steps are claimed with `FOR UPDATE SKIP LOCKED` and completed with guarded
writes (`WHERE locked_by = <worker> AND status = 'running'`). Lock order is always
execution, then steps. See `docs/architecture/adr/0002-postgres-as-the-queue.md`.

**Errors.** Raise the typed errors in `core/errors.py`; nodes raise `NodeError(code,
message, retryable)`. The handlers turn them into the one envelope every response uses:
`{"error": {"code", "message", "request_id", "details?"}}`.

## A reference resource

API keys are the smallest complete slice of the stack. Read them in this order:

1. `api/routes/api_keys.py`: URL, role dependency, request and response models
2. `services/api_keys.py`: generation, hashing with the pepper, audit event, commit
3. `repositories/api_keys.py`: the queries, always scoped by workspace
4. `tests/integration/test_identity.py`: the behaviour end to end

A node type is the reference for the engine: `nodes/core.py` (`core.transform`), its
config model, `run()`, and `tests/unit/test_nodes_core.py`.
