# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-23

First public release.

### Added

- A visual editor on a React Flow canvas: a searchable node palette, typed ports, connection
  rules, forms generated from each node's JSON schema, inline validation, autosaved drafts
  with conflict detection, single-node test runs, test runs of the whole draft, and a webhook
  panel with the URL and the signing rules.
- Triggers: manual runs with a payload; webhooks with HMAC-SHA256 or bearer authentication,
  timestamped signatures against replay, idempotency keys and optional synchronous answers;
  five-field cron schedules in any IANA time zone with defined daylight-saving behaviour;
  intervals; events with name patterns and payload filters, with `overlap: skip` for
  schedules.
- 21 node types: transform (JMESPath and templates), set variables, publish event, if,
  switch, merge, loop over items, wait, stop, HTTP request, email (SES), Slack message, S3
  get and put, SQS publish and Postgres query (read-only by default).
- A durable engine in Postgres: steps claimed with `FOR UPDATE SKIP LOCKED`, guarded writes,
  heartbeats and a reaper, retries with exponential backoff and jitter, node and execution
  timeouts, cancellation, resume from the failed step, retry from the start, dead letters,
  per-workflow concurrency limits, branch skipping and merges by dead-path elimination,
  loops with scopes.
- A leader-elected scheduler on Valkey that fires each schedule tick exactly once, wakes
  waiting steps, enforces deadlines, admits queued executions and prunes old history.
- A credentials vault with per-credential KMS data keys bound to their workspace, write-only
  secrets and value-based redaction; an outbound network guard against SSRF and DNS
  rebinding; S3 and SQS allowlists.
- Draft and immutable published versions, restore, JSON export and import, duplicate, and a
  gallery of seven templates seeded by `make demo` with two weeks of real execution history.
- Executions list with filters and cursors; an execution view with the graph as it ran, a
  timeline, step input, output and logs; a dashboard with success rate, daily volume, the
  slowest workflows and recent failures; an event bus page; dead letters; settings for
  workspace defaults, variables, members, API keys and the audit log.
- Workspaces with owner, editor and viewer roles, workspace API keys, an append-only audit
  log, Prometheus metrics, health and readiness probes and structured JSON logs.
- Docker images, a Compose stack on the Floci AWS emulator provisioned by Terraform,
  Terraform modules and environments for local, AWS dev and AWS prod, CI workflows, the
  Playwright suites, the QA crawl and the documentation set.
