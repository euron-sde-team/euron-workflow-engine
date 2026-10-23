# ADR 0002: Postgres is the work queue

## Status

Accepted.

## Context

An execution is a set of steps whose state must survive crashes, deploys and retries:
which steps are ready, which are running and on which worker, which wait until a time,
which failed and how often. The engine must never run a step twice concurrently, never
lose a step, and must be able to resume an execution from the step that failed, days
later. That state lives in Postgres anyway, because the execution history, the dashboard
and the API read it.

A separate broker (SQS, RabbitMQ, Redis streams) would hold a second copy of "what should
run next". Every handover between the broker and the database is a place where the two
can disagree: a message delivered for a step that was cancelled, a step committed whose
message was never sent, a redelivery after a worker crash while the database still says
"running".

## Decision

- Steps are rows in `execution_steps`; the queue is a partial index on
  `(available_at) WHERE status = 'queued'`.
- Workers claim with one statement:
  `UPDATE execution_steps SET status = 'running', locked_by = <worker>, attempt = attempt + 1, ...
  WHERE id IN (SELECT id ... WHERE status = 'queued' AND available_at <= now()
  ORDER BY available_at LIMIT n FOR UPDATE SKIP LOCKED) RETURNING ...`.
  Racing workers skip each other's rows instead of blocking on them.
- Every completion is a guarded write: `... WHERE id = <step> AND status = 'running' AND
  locked_by = <worker>`. A worker whose claim was reaped (heartbeat older than
  `STEP_STALE_S`) or cancelled loses the write and discards its result.
- Running steps heartbeat every `STEP_HEARTBEAT_S`; the scheduler's reaper requeues stale
  claims, so a crashed worker delays a step but never loses it.
- Lock order is always execution, then steps, so routing (which updates both) cannot
  deadlock with a claim.
- Redis carries wake-up signals (`wfe:wake`) so idle workers react within milliseconds,
  but only as a hint: workers also poll every `WORKER_POLL_INTERVAL_MS`, so a lost signal
  costs latency, never correctness.
- Per-workflow concurrency limits are enforced at admission: an execution beyond the limit
  stays `queued` and is admitted, in order, when one finishes.

## Consequences

Positive:

- One transaction moves a step and records its result, its log lines and the steps it
  unlocks. There is no dual write and no outbox.
- Cancellation, resume from a failed step, retries with backoff, waits (a step with a
  future `available_at`) and dead letters are all plain row updates with the same
  guarantees.
- The integration suite proves the claim with 12 concurrent claimers and no double claim.

Trade-offs:

- Throughput is bounded by Postgres write capacity. For the workloads this product targets
  (thousands of steps a minute on a modest instance) that is ample; the partial indexes
  keep the queue scan small however long the history grows.
- Polling costs a cheap indexed query per worker per interval when idle.
- Long-running steps hold no transaction (claims commit immediately), so the design relies
  on heartbeats and the reaper rather than on the database to notice a dead worker.

## Alternatives considered

- **SQS or RabbitMQ.** Durable delivery, but at-least-once with visibility timeouts and a
  second source of truth; resume and cancel would need compensating messages.
- **Redis streams or lists.** Fast, but Redis is configured without persistence here and
  is deliberately never the source of truth.
- **Temporal.** Durable execution done properly, at the cost of another cluster to run and
  a programming model aimed at code, not at a visual editor.
