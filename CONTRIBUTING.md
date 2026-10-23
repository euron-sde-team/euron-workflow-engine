# Contributing

Thanks for helping improve Euron WorkflowEngine. This guide covers the workflow, the bar a
change has to clear, and the conventions the codebase follows.

## Ground rules

- **Open an issue first** for anything larger than a bug fix or a docs tweak, so we can
  agree on the approach before you invest time.
- **One concern per pull request.** A refactor and a feature are two PRs.
- **Security issues go through private reporting**, never a public issue. See
  [SECURITY.md](SECURITY.md).
- By contributing you agree your work is released under the [MIT License](LICENSE).

## Development setup

Requirements: Docker with Compose v2, Python 3.12 with [uv](https://docs.astral.sh/uv/), and
Node.js 22 with pnpm 9 (`corepack enable`).

```bash
make up          # Postgres, Redis, the AWS emulator (provisioned by Terraform), Mailpit, api, workers, web
make demo        # a demo workspace with templates, credentials and two weeks of execution history
make test        # unit tests for the API (pytest) and the web app (Vitest)
```

[docs/guides/quickstart-local.md](docs/guides/quickstart-local.md) walks through the local
stack in detail.

## Before you open a pull request

Each of these must pass:

```bash
make lint typecheck test
make test-integration                  # the API, workers and scheduler against real Postgres, Redis and the AWS emulator
make e2e                               # when you touched a user flow, the web app or infrastructure
make tf-validate tf-lint tf-security   # when you touched infra/terraform
make sanitize                          # no credentials, account ids or resource ids
```

## Conventions

**Layers (api).** Routes declare the URL, the request and response models and the access
dependency, nothing else. Services hold the business rules, transactions and cache
invalidation. Repositories are the only code that touches the database.
[apps/api/README.md](apps/api/README.md) has the rules and a reference resource to copy.

**The engine core is pure.** Graph validation, routing, the cron parser, expressions and
templates live in `apps/api/src/workflow_engine/engine` and do no I/O, so every rule about
how a workflow runs is covered by fast unit tests. The worker and the scheduler only move
state between Postgres and those functions.

**Every queue write is guarded.** A worker may only change a step it holds:
`WHERE id = :id AND locked_by = :worker AND status = 'running'`, and a write that matches no
row means the claim was lost. Read [ADR-0002](docs/architecture/adr/0002-postgres-as-the-queue.md)
before changing anything in `repositories/executions.py`, `services/steps.py` or
`services/engine.py`.

**A new node type** is one module in `apps/api/src/workflow_engine/nodes/`: a Pydantic
config model (it becomes the editor's form and the validation rules), a `run` coroutine and
a unit test. Nodes never execute user-supplied code.

**Workspace isolation is structural.** Every repository method that reads workspace data
takes the workspace id as a required argument and filters by it, and the access dependency
resolves the caller's role before a route runs. The integration suite calls every workspace
route as a non-member and asserts that nothing is returned or changed.

**Configuration is validated.** A new environment variable is declared in
`apps/api/src/workflow_engine/core/config.py` and documented in
[docs/guides/configuration.md](docs/guides/configuration.md) in the same PR.
Security-relevant settings are enforced at boot when `APP_ENV=production`.

**Database changes are new migrations.** `uv run alembic revision -m "describe it"` in
`apps/api`. Never edit an applied migration.

**Comments explain why.** The code says what it does. Comments are for the constraint, the
incident, or the trade-off that made it this way.

**Style.** ruff (lint and format) and mypy in strict mode for Python; ESLint, Prettier and
strict TypeScript for the web app.

## Commit messages

Imperative mood with a scope: `engine: skip merge inputs from untaken branches`,
`web: show retry attempts on the execution timeline`. Explain the *why* in the body when it
is not obvious.

## Architecture decisions

A change that alters a documented decision (queueing, scheduling, expression language,
credential encryption, deployment topology) needs a new ADR in
[docs/architecture/adr/](docs/architecture/adr/), using the existing ones as a template.
