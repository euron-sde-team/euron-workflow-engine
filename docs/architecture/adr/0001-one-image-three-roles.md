# ADR 0001: One image for the API, the workers and the scheduler

## Status

Accepted.

## Context

WorkflowEngine has three kinds of work: answering HTTP (the web app, the REST API and
webhooks), executing steps, and firing schedules plus housekeeping (waking waiting steps,
reaping stale claims, enforcing deadlines, pruning history). All three need the same
domain code: the node registry, the routing engine, the vault, the repositories. Splitting
them into separate services would mean either a shared library released in lockstep or
duplicated logic that drifts.

The scheduler also has to run in exactly one place at a time, but a dedicated singleton
service is a single point of failure that needs its own failover story.

## Decision

- One Python package (`workflow_engine`) and one container image
  (`infra/docker/api.Dockerfile`) provide every role:
  - `uvicorn workflow_engine.main:create_app --factory`: the API (default command);
  - `wfe worker`: claims and runs steps; with `SCHEDULER_ENABLED=true` (the default) it
    also stands for the scheduler election (ADR 0003);
  - `wfe migrate`, `wfe user create`, `wfe demo seed`, `wfe demo-apis`: one-off commands.
- The code is layered (`api/routes` to `services` to `repositories`), and `runtime/`
  holds the long-running loops (executor, scheduler, leader election, presence) that only
  the worker starts.
- The API never executes steps itself, except the single-node test run an editor asks for
  explicitly, which stores nothing.

## Consequences

Positive:

- One build, one vulnerability scan, one version number. A deployment cannot run an API
  and workers that disagree about the node catalog or the definition format.
- Scaling is a replica count per role: more API tasks for webhook bursts, more worker
  tasks for step throughput. There is no scheduler service to scale or fail over.
- Locally, `docker compose` runs the same image with a different command per service.

Trade-offs:

- The API image carries worker-only code (and the other way round). The package is small,
  so the cost is a few megabytes.
- A bug in shared code reaches every role at once; the integration suite runs the real
  worker and scheduler against the real API for that reason.

## Alternatives considered

- **Separate services for the API, the executor and the scheduler.** Cleaner process
  boundaries, but three release trains and a scheduler singleton to babysit.
- **A Celery or RQ worker pool.** Adds a broker and a second state store whose view of a
  job can disagree with the database (see ADR 0002).
