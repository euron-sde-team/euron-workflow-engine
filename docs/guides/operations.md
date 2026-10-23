# Operations

Running WorkflowEngine on AWS day to day: backups, migrations, rotation, scaling, alarms,
logs and the housekeeping the scheduler does on its own.

## What runs on its own

The elected scheduler (one worker at a time) runs these every tick (`SCHEDULER_TICK_MS`):

| Sweep | What it does |
| --- | --- |
| Fire schedules | Starts due cron and interval triggers once per tick (compare-and-set plus an idempotency key) |
| Wake | Makes steps whose wait ended ready again |
| Reap | Requeues running steps whose heartbeat is older than `STEP_STALE_S` (a crashed or stopped worker) |
| Deadlines | Fails executions past their workflow timeout and cancels their active steps |
| Admit | Starts queued executions when their workflow's concurrency limit frees up |
| Prune | Deletes finished executions (with steps, logs and dead letters) and events older than the workspace's retention, in batches |

Nothing needs a cron job outside the application.

## Backups and point-in-time recovery

Postgres holds everything: workflows, versions, executions, the queue, credentials (sealed),
the audit log. Valkey holds nothing that cannot be lost.

- RDS automated backups: 3 days in `aws-dev`, 14 in `aws-prod`, with point-in-time
  recovery to any second inside the window.
- Restoring means creating a new instance from a snapshot or a point in time, then pointing
  `DATABASE_URL` (the module's `address`) at it and redeploying.
- Sealed credentials restore with the database; they open again because the vault key is
  unchanged. Do not schedule the vault key for deletion while any backup may still be
  restored.
- The workflow data bucket is versioned; superseded versions are kept for 90 days.

## Migrations

Migrations are Alembic revisions shipped in the image. They run:

- when an API task starts with `MIGRATE_ON_BOOT=true` (the default on AWS), under a
  transaction-scoped advisory lock, so many tasks starting together migrate once;
- or on demand: `make aws-migrate ENV=aws-prod`.

Every revision is backwards compatible with the previous release for one deploy (add
columns nullable, backfill, then tighten in a later release), so old and new tasks can run
side by side during a rolling deployment.

## Secret rotation

| Secret | How | Effect |
| --- | --- | --- |
| `SESSION_SECRET` | Put a new value into `<name_prefix>/app` in Secrets Manager (keep the other key), then force a new deployment of api and worker | Everyone is signed out |
| `API_KEY_PEPPER` | Same secret, the other key | Every API key stops working; create new ones |
| Database password | RDS rotates it in its own secret; tasks read it per new connection | None |
| Valkey auth token | Change the replication group's token and the `REDIS_URL` in `<name_prefix>/cache`, then redeploy | Brief reconnects |
| A stored credential | Edit it in the web app (Credentials, *Edit or rotate*); the new value is sealed with a new data key | The next step that uses it gets the new value |

```bash
aws secretsmanager get-secret-value --secret-id wfe-prod/app --query SecretString --output text > /tmp/app.json
# edit ONE key, 64 random characters, different from the other
aws secretsmanager put-secret-value --secret-id wfe-prod/app --secret-string file:///tmp/app.json
rm /tmp/app.json
aws ecs update-service --cluster wfe-prod --service api --force-new-deployment
aws ecs update-service --cluster wfe-prod --service worker --force-new-deployment
```

## KMS key rotation

Both keys rotate automatically every year (`enable_key_rotation`). Old key material stays
available for decryption, so nothing is re-encrypted and no credential needs to be saved
again.

## Scaling

| Signal | Action |
| --- | --- |
| Steps wait in `queued` (dashboard *Queue*, `wfe_queue_depth{kind="steps",state="ready"}`) while workers are busy | More worker tasks (`worker_min_count`) or a higher `WORKER_CONCURRENCY` |
| Worker CPU above 60% | The autoscaler adds tasks up to `worker_max_count` |
| `DatabaseConnections` alarm | Fewer connections per process (`DATABASE_POOL_SIZE`) or a larger instance |
| Webhook latency | More API tasks; check the per-trigger rate limit first |

## Alarms and dashboard

The `observability` module sends every alarm to the SNS topic `<name_prefix>-alarms`
(subscribe an email with `alarm_email`, or anything else to the topic):

| Alarm | Meaning | First look |
| --- | --- | --- |
| `<service>-5xx` | The API or web tasks answer 5xx | API logs for `error` lines |
| `<service>-unhealthy` | Tasks fail load balancer health checks | ECS events, task logs at start-up |
| `<service>-cpu`, `<service>-memory` | Sustained above 85% | Scale out, or look for a runaway workflow |
| `workers-down` | No worker task is running: nothing executes, no schedule fires | ECS service events, the last worker logs |
| `<queue>-dead-letters` | A consumer of a workflow queue gave up on messages | The consumer, not WorkflowEngine |
| `db-cpu`, `db-storage`, `db-connections` | Database pressure | Retention settings, connection pools, instance size |

The CloudWatch dashboard `<name_prefix>` shows requests and errors, latency, CPU and
memory per service, running workers and the database.

The workers also export Prometheus metrics on port 9100 and the API on `/metrics`
(`wfe_*`: executions started and finished, step durations and retries per node type,
queue depth, leader status, schedule fires, webhook outcomes, vault operations).

## Logs

Every process logs JSON lines to CloudWatch (`/wfe/<name_prefix>/<service>`). API lines
carry the request id that the error envelope returns to clients; worker lines carry the
execution id, step id and node.

```bash
aws logs tail /wfe/wfe-prod/worker --since 30m --filter-pattern '{ $.level = "error" }'
```

Per-execution logs (attempts, retries scheduled, HTTP status lines, rows returned) are in
the web app on each execution, and in the API under `/executions/{id}/logs`.

## Routine checks

- Dead letters: open ones mean a workflow failed after every retry. Fix the cause, then
  retry the letter (the execution resumes from the failed step) or discard it.
- The audit log: `credential.*`, `member.*` and `api_key.*` actions.
- API keys without an expiry and not used for months: revoke them.
