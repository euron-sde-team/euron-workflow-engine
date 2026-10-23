# Configuration

The API, the workers and the CLI read their configuration from environment variables
(`workflow_engine.core.config.Settings`, validated at start-up). The web app reads two
variables at request time from `/env.js`, so one image serves every environment.

In production (`APP_ENV=production`) the processes refuse to start when the configuration
is unsafe: development or short secrets, equal session secret and pepper,
`COOKIE_SECURE=false`, a wildcard CORS origin, a vault other than KMS, an emulator
endpoint, or the private-network guard turned off. The error lists every problem at once.

## Application

| Variable | Default | Meaning |
| --- | --- | --- |
| `APP_ENV` | `development` | `development`, `test` or `production` |
| `PRODUCT_NAME` | `Euron WorkflowEngine` | Name the API reports in `/api/v1/system/info` |
| `LOG_LEVEL` | `info` | `debug`, `info`, `warning`, `error` |
| `LOG_FORMAT` | `json` | `json` (one object per line) or `console` |
| `WEB_URL` | `http://localhost:3130` | Origin of the web app; links in emails and the CSRF allowlist |
| `API_URL` | `http://localhost:8130` | Public origin of the API |
| `PUBLIC_HOOKS_URL` | `API_URL` | Origin printed for webhook URLs, when it differs from `API_URL` |
| `CORS_ORIGINS` | `http://localhost:3130,http://127.0.0.1:3130` | Comma-separated origins allowed to call the API with credentials |
| `ALLOW_SIGNUP` | `false` | Let anyone create an account on the sign-in page (the first account can always be created) |

## Database and Valkey

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://wfe:wfe@localhost:5453/wfe` | Postgres 16; the system of record and the work queue |
| `DATABASE_SECRET_ARN` | none | On AWS: the RDS-managed secret holding the password, read for each new connection |
| `DATABASE_POOL_SIZE` | `10` | Connections per process |
| `DATABASE_MAX_OVERFLOW` | `10` | Extra connections under load |
| `DATABASE_ECHO` | `false` | Log every SQL statement (debugging only) |
| `MIGRATE_ON_BOOT` | `false` | Apply migrations when the API or a worker starts (advisory-locked, safe with many replicas) |
| `REDIS_URL` | `redis://localhost:6413/0` | Valkey or Redis: leader lock, wake-ups, cancel signals, rate limits, caches |

## Sessions and API keys

| Variable | Default | Meaning |
| --- | --- | --- |
| `SESSION_SECRET` | development value | Signs session tokens. At least 32 random characters in production |
| `SESSION_TTL_HOURS` | `168` | Session lifetime |
| `API_KEY_PEPPER` | development value | Keys the HMAC of stored API keys. Different from `SESSION_SECRET` |
| `COOKIE_SECURE` | `false` | `true` behind HTTPS (required in production) |
| `COOKIE_DOMAIN` | none | Set when the web app and the API share a parent domain |

## AWS and the credentials vault

| Variable | Default | Meaning |
| --- | --- | --- |
| `AWS_REGION` | `us-east-1` | Region of KMS, S3, SQS and SES |
| `AWS_ENDPOINT_URL` | none | Emulator endpoint (Floci); never set in production |
| `VAULT_PROVIDER` | `local` | `kms` (envelope encryption with AWS KMS) or `local` (key derived from `VAULT_LOCAL_KEY`, laptops only) |
| `KMS_KEY_ID` | none | The vault key: id, ARN or alias |
| `VAULT_LOCAL_KEY` | development value | Root secret for the `local` vault provider |
| `MAIL_FROM` | `Euron WorkflowEngine <automations@wfe.example.test>` | Sender of the email node; must be a verified SES identity |
| `SES_CONFIGURATION_SET` | none | Configuration set for every message (TLS, reputation, suppression) |
| `WORKFLOW_DATA_BUCKET` | none | Default bucket of the S3 nodes |
| `S3_ALLOWED_BUCKETS` | empty | Other buckets the S3 nodes may use (comma-separated) |
| `SQS_ALLOWED_QUEUES` | empty | Queues the SQS node may publish to (names or URLs) |

## Outbound network policy

| Variable | Default | Meaning |
| --- | --- | --- |
| `OUTBOUND_ALLOW_PRIVATE_NETWORKS` | `false` | `true` lets the HTTP, Slack and Postgres nodes reach private, loopback and link-local addresses. Refused in production |
| `OUTBOUND_ALLOWED_HOSTS` | empty | Host names allowed even when they resolve to private addresses, for example an internal API |
| `HTTP_USER_AGENT` | `EuronWorkflowEngine/0.1 (...)` | User agent of the HTTP request node |

## Workers and the scheduler

| Variable | Default | Meaning |
| --- | --- | --- |
| `WORKER_CONCURRENCY` | `8` | Steps a worker runs at once |
| `WORKER_POLL_INTERVAL_MS` | `1000` | Polling interval when no wake-up signal arrives |
| `WORKER_METRICS_PORT` | `0` (off) | Port of the worker's Prometheus endpoint (`/metrics`); compose and AWS use `9100` |
| `STEP_HEARTBEAT_S` | `10` | How often a running step proves its worker is alive |
| `STEP_STALE_S` | `60` | A running step without a heartbeat for this long is requeued |
| `SCHEDULER_ENABLED` | `true` | Stand for the scheduler election (`wfe worker --no-scheduler` overrides) |
| `SCHEDULER_TICK_MS` | `1000` | Scheduler tick: schedules, wake-ups, reaping, deadlines, admissions |
| `LEADER_TTL_S` | `15` | Leader lock lifetime; the longest schedule pause after a leader dies |
| `SHUTDOWN_GRACE_S` | `30` | How long a stopping worker lets running steps finish |

## Limits

| Variable | Default | Meaning |
| --- | --- | --- |
| `MAX_PAYLOAD_KB` | `1024` | Largest trigger payload or step output stored |
| `WEBHOOK_MAX_BODY_KB` | `1024` | Largest webhook body accepted |
| `EVENT_MAX_DEPTH` | `5` | Longest chain of events publishing events |
| `DEFAULT_RETENTION_DAYS` | `30` | Retention for new workspaces (each workspace can change it) |
| `RATE_LIMIT_LOGIN` | `10` | Sign-in attempts a minute per client address |
| `RATE_LIMIT_WEBHOOK` | `600` | Requests a minute per webhook trigger |
| `RATE_LIMIT_TEST_RUN` | `60` | Single-node test runs a minute per caller |
| `RATE_LIMIT_EVENTS` | `600` | Events published a minute per caller |

## Local stacks only

| Variable | Default | Meaning |
| --- | --- | --- |
| `DEMO_PASSWORD` | none | Password of every demo account (`make demo` passes `WFE_DEMO_PASSWORD`) |
| `DEMO_APIS_URL` | `http://localhost:9131` | Where the demo workflows find the demo APIs |

## Web app

| Variable | Default | Meaning |
| --- | --- | --- |
| `API_URL` | `http://localhost:8130` | Address the browser calls the API at |
| `PRODUCT_NAME` | `Euron WorkflowEngine` | Name in the header and the page titles |

## Compose (`deploy/compose/.env`)

`make env` writes this file once with random values. Every host port can be overridden here:

| Variable | Default |
| --- | --- |
| `WFE_SESSION_SECRET`, `WFE_API_KEY_PEPPER`, `WFE_DEMO_PASSWORD` | generated |
| `WFE_WEB_PORT` | `3130` |
| `WFE_API_PORT` | `8130` |
| `WFE_PG_PORT` | `5453` |
| `WFE_REDIS_PORT` | `6413` |
| `WFE_FLOCI_PORT` | `4613` |
| `WFE_MAILPIT_PORT` | `9130` |
| `WFE_DEMO_APIS_PORT` | `9131` |
| `WFE_LOG_LEVEL`, `WFE_PRODUCT_NAME` | `info`, `Euron WorkflowEngine` |
