# ADR 0003: A leader-elected scheduler that stays correct without its lock

## Status

Accepted.

## Context

Cron and interval triggers must fire once per tick, in the trigger's time zone, whether
one worker runs or twenty. Housekeeping (waking steps whose wait ended, reaping stale
claims, enforcing execution deadlines, admitting queued executions, pruning history) must
run somewhere, ideally once. A dedicated scheduler process is a single point of failure;
running the scheduler in every worker multiplies the work and risks duplicate fires.

## Decision

- Every worker stands for election on one Redis key:
  `SET wfe:scheduler:leader <id> NX PX <ttl>` to acquire, a Lua script that renews only
  while the value is still its own id, another that deletes only its own lock on shutdown.
  The TTL is `LEADER_TTL_S` (15 s); the leader renews well within it.
- Only the leader runs the scheduler tick (every `SCHEDULER_TICK_MS`).
- Firing a schedule is safe even with two leaders during a handover or a network
  partition:
  - the trigger row's `next_fire_at` is advanced with a compare-and-set
    (`UPDATE ... WHERE id = <trigger> AND next_fire_at = <due>`); only one scheduler wins;
  - the execution is created with the idempotency key `schedule:<trigger_id>:<due>`, so
    even a winner that retries after a failure cannot create a second run for the same
    tick.
- Overdue ticks (the leader was down) are coalesced: the trigger fires once and moves to
  its next future time, instead of replaying every missed tick.
- A cron or interval trigger configured with `overlap: skip` does not start while its
  previous run is still queued or running, so a slow job never piles up behind itself.
- Every other sweep is idempotent by construction (guarded updates), so running it twice
  is harmless.

## Consequences

Positive:

- No singleton to deploy, monitor or fail over: losing the leader pauses schedules for at
  most one TTL, then another worker takes over.
- Correctness never depends on Redis. The integration suite runs two schedulers against
  one trigger and asserts exactly one execution per tick.

Trade-offs:

- Up to `LEADER_TTL_S` of schedule delay after the leader dies.
- Housekeeping latency depends on the tick interval, which is a trade between promptness
  and database load (one second by default).

## Alternatives considered

- **Postgres advisory lock for leadership.** Works, but ties a pooled connection to a
  session-level lock for the life of the process, which fights the connection pool.
- **Every worker schedules, deduplicated by the idempotency key alone.** Correct, but
  multiplies the scheduler queries by the worker count for no benefit.
- **An external cron (EventBridge Scheduler, Kubernetes CronJob).** One entry per user
  schedule, created and deleted as workflows change: another API to keep in sync, and it
  would not exist locally.
