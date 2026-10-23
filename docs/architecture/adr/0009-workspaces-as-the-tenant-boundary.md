# ADR 0009: Workspaces are the tenant boundary inside one deployment

## Status

Accepted.

## Context

One WorkflowEngine deployment usually serves several teams: operations, finance, sales.
Each team owns its workflows, credentials, variables and history, and must not see or run
another team's. People belong to more than one team. Running one deployment per team
multiplies the infrastructure and the upgrades for no isolation benefit the data model
cannot give.

## Decision

- A **workspace** owns everything a team builds and runs: workflows and their versions,
  triggers, executions and steps, credentials, variables, events, dead letters, API keys
  and the audit log. Every one of those tables carries `workspace_id`.
- Membership gives a role per workspace: **owner** (members, settings, API keys, audit
  log), **editor** (build, publish, run, credentials, variables, dead letters) or
  **viewer** (read workflows, executions and the dashboard). API keys act as editor or
  viewer in exactly one workspace.
- Every route resolves the workspace from the URL (`/api/v1/workspaces/{workspace}/...`,
  slug or id) and checks the caller's role before anything else. Every repository method
  takes the workspace id and filters by it, so a guessed id from another workspace returns
  404, not 403, and leaks nothing.
- Webhooks are addressed per workspace (`/hooks/{workspace}/{path}`), events are
  delivered only inside the workspace that published them, and KMS encryption contexts
  include the workspace id (ADR 0006).
- Workspace-level settings (time zone, retention, default timeout) apply to the
  workspace's schedules, dashboard and pruning.

## Consequences

Positive:

- One deployment, one upgrade, one set of alarms for every team.
- Isolation is enforced in one place per layer (route dependency, repository filter) and
  covered by integration tests that try cross-workspace access.

Trade-offs:

- Workers are shared: a workspace that floods the queue slows the others. Per-workflow
  concurrency limits, per-trigger rate limits on webhooks and per-caller limits on events
  and test runs bound the damage; there is no per-workspace worker pool.
- The outbound network allowlist, the S3 bucket allowlist and the SQS queue allowlist are
  deployment-wide, not per workspace.

## Alternatives considered

- **A deployment per team.** Strongest isolation, highest cost, and no shared templates or
  people across teams.
- **Postgres row-level security.** A second line of defence worth adding later; today the
  repository filter is the single enforcement point and is tested as such.
