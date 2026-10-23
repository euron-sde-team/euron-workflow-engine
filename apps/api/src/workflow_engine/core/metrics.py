"""Prometheus metrics: `GET /metrics` on the API, `WORKER_METRICS_PORT` on workers.

One process per container (scale out with containers, not uvicorn workers), so the default
registry is accurate without multiprocess mode. Queue depth is computed by the scheduler
leader and read from Redis at scrape time, so every process reports the same numbers.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "wfe_http_requests_total", "HTTP requests by route template.", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "wfe_http_request_duration_seconds",
    "HTTP request latency by route template.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
EXECUTIONS_STARTED = Counter(
    "wfe_executions_started_total", "Executions accepted, by trigger kind.", ["trigger"]
)
EXECUTIONS_FINISHED = Counter(
    "wfe_executions_finished_total", "Executions that reached a final status.", ["status"]
)
EXECUTION_DURATION = Histogram(
    "wfe_execution_duration_seconds",
    "Time from start to final status.",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 300, 900, 3600),
)
STEPS = Counter(
    "wfe_steps_total", "Step attempts by node type and outcome.", ["node_type", "outcome"]
)
STEP_DURATION = Histogram(
    "wfe_step_duration_seconds",
    "Duration of one step attempt by node type.",
    ["node_type"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 120),
)
STEP_RETRIES = Counter(
    "wfe_step_retries_total", "Retries scheduled after a failed attempt.", ["node_type"]
)
STEPS_REAPED = Counter("wfe_steps_reaped_total", "Running steps recovered from lost workers.")
DEAD_LETTERS = Counter("wfe_dead_letters_total", "Steps parked after exhausting retries.")
SCHEDULE_FIRES = Counter("wfe_schedule_fires_total", "Schedule ticks fired.", ["kind", "outcome"])
SCHEDULER_LEADER = Gauge("wfe_scheduler_leader", "1 while this process holds the leader lock.")
WEBHOOKS = Counter("wfe_webhook_requests_total", "Webhook ingress by outcome.", ["outcome"])
EVENTS_PUBLISHED = Counter("wfe_events_published_total", "Events on the bus by source.", ["source"])
VAULT_OPERATIONS = Counter(
    "wfe_vault_operations_total", "Credential encrypt and decrypt calls.", ["operation", "provider"]
)
QUEUE_DEPTH = Gauge("wfe_queue_depth", "Steps and executions by state.", ["kind", "state"])
WORKER_SLOTS_BUSY = Gauge("wfe_worker_slots_busy", "Steps running in this worker.")
