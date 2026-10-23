# Security

How WorkflowEngine protects the things that matter in a workflow tool: the credentials it
holds, the systems its workflows can reach, and the integrity of what runs. The STRIDE
analysis with residual risks is in [threat-model.md](threat-model.md); decisions are in
the [ADRs](adr/README.md). To report a vulnerability, see [SECURITY.md](../../SECURITY.md).

## Principles

1. **No code execution.** Editors configure nodes; they never write code that the worker
   runs. Expressions are JMESPath and templates are logic-free (ADR 0004).
2. **Credentials are write-only.** Stored sealed, decrypted only inside the step that needs
   them, never returned by the API, redacted from everything a step stores (ADR 0006).
3. **Workflows reach only what the deployment allows.** Private networks, cloud metadata,
   other buckets and other queues are refused unless an operator lists them.
4. **Every tenant query is scoped.** The workspace is resolved and the role checked before
   a route runs, and every repository call filters by workspace (ADR 0009).
5. **Production refuses unsafe configuration** at boot (`Settings.production_problems`).

## Identity and sessions

| Control | Detail |
| --- | --- |
| Passwords | Argon2id, 64 MiB memory, time cost 3, parallelism 2; at least 10 characters; unknown emails are verified against a dummy hash so timing does not reveal accounts |
| Sessions | HS256 JWT (issuer and audience checked) in an `httpOnly`, `SameSite=Lax` cookie (`wfe_session`), `Secure` in production, 7 days by default (`SESSION_TTL_HOURS`) |
| Sign out | The token id goes on a Redis denylist until it expires; "sign out everywhere" and password changes bump the user's session version, which invalidates every token at once |
| CSRF | Unsafe methods with a cookie session must carry an `Origin` (or `Referer`) from `CORS_ORIGINS` or `WEB_URL`; anything else is refused with `csrf` |
| CORS | Explicit origins only; production refuses `*` |
| API keys | `wfk_<prefix>_<secret>`: only an HMAC-SHA256 of the secret, keyed with `API_KEY_PEPPER`, is stored; shown once at creation; role `viewer` or `editor` in one workspace; optional expiry; revocable; last use recorded |
| Sign-in throttling | 10 attempts a minute per client address (`RATE_LIMIT_LOGIN`), counted in Valkey so every API replica shares the budget |

Production refuses to start when `SESSION_SECRET` or `API_KEY_PEPPER` is the development
default, shorter than 32 characters, or equal to the other.

## Authorization

| Role | Can |
| --- | --- |
| owner | Everything below, plus members, workspace settings, API keys and the audit log |
| editor | Create, edit, publish, activate, run and delete workflows; credentials; variables; publish events; cancel, resume and retry executions; retry and discard dead letters; test single nodes |
| viewer | Read workflows, versions, executions, step input and output, logs, events and the dashboard |

The route dependency resolves the workspace from the path and the principal's membership
(or the API key's workspace) and raises 404 for non-members, so workspace ids and slugs
cannot be probed. Every repository method takes the workspace id.

## The credentials vault

- Sealed with a per-credential AES-256 data key from KMS `GenerateDataKey`, encryption
  context `{workspace_id, credential_id}`, AES-256-GCM with the context as associated data.
  The plaintext data key never leaves the process and is not cached (ADR 0006).
- On AWS the vault key is its own customer-managed key with annual rotation. The API and
  worker task roles may call `GenerateDataKey` and `Decrypt` on it only when the encryption
  context contains exactly `workspace_id` and `credential_id`.
- The API returns name, type, public fields (a host, a user name), the names of the secret
  fields, the key provider, a version counter, the workflows that use the credential and
  when it was last used. Editing with a blank secret keeps the stored one.
- A credential still referenced by a workflow cannot be deleted; the error names the
  workflows.
- Webhook signing secrets are cached in process for 60 seconds so a burst of webhooks does
  not cost a KMS call each.
- At run time a node receives only the credentials its own configuration references.
  Every string value of those credentials (four characters or longer, public fields
  included) is replaced with `[redacted]` in step output, step errors, execution logs and
  node test results before anything is stored or returned.

## Webhook ingress

| Control | Detail |
| --- | --- |
| Authentication | Per trigger: HMAC-SHA256 over the raw body (`X-Signature: sha256=<hex>` by default, header and prefix configurable), optionally over `<timestamp>.<body>` with a tolerance window (default 300 s) against replay; or a shared bearer token; or none, which the editor flags |
| Comparison | Constant time |
| Size | Bodies above `WEBHOOK_MAX_BODY_KB` (1 MiB) are refused before parsing |
| Replays and retries | An `Idempotency-Key` header (name configurable) returns the original execution instead of starting a second one |
| Rate limit | `RATE_LIMIT_WEBHOOK` requests a minute per trigger |
| Exposure | Only published, active workflows have live webhook paths; unknown paths answer 404 |

## Outbound network guard

The HTTP request, Slack and Postgres nodes act with the deployment's network position, so
without a guard any editor could reach the cloud metadata service, the database, Valkey or
an internal admin panel.

- Every outbound connection resolves the host, checks **every** resolved address, and
  then connects to the checked address (not to the name), so a DNS answer that changes
  between check and connect (rebinding) cannot slip through.
- Refused: private (RFC 1918, unique local), loopback, link-local (including
  `169.254.169.254` and `fd00:ec2::254`), multicast, reserved and unspecified addresses.
- Redirects are followed hop by hop through the same guard.
- `OUTBOUND_ALLOWED_HOSTS` lists host names that may resolve privately (the local stack
  allows `demo-apis` and `postgres`); `OUTBOUND_ALLOW_PRIVATE_NETWORKS=true` turns the
  guard off and is refused in production.
- On AWS the task security groups allow egress on 443 and the ports in
  `workflow_egress_ports` (80 by default) only.
- Limits: per-request timeout, `max_response_kb` (1 MiB default, 10 MiB maximum) and a
  bounded number of redirects.

## Data nodes

| Node | Control |
| --- | --- |
| S3 get and put | Only `WORKFLOW_DATA_BUCKET` and the buckets in `S3_ALLOWED_BUCKETS`; SSE-KMS on the data bucket; the task role can read and write that bucket only |
| SQS publish | Only queues in `SQS_ALLOWED_QUEUES`; the task role can send to the workflow queues only |
| Email | SES from `MAIL_FROM` (a verified identity) through a configuration set that requires TLS and suppresses bounces and complaints |
| Postgres query | Read-only transactions by default (`read_write` is an explicit node setting), parameters bound by the driver, statement timeout (30 s default, 120 s maximum), row cap (500 default) |
| Slack message | A Slack-compatible incoming-webhook URL stored as a credential, through the outbound guard |

## Engine integrity

- **No double execution.** Claims use `FOR UPDATE SKIP LOCKED`; results are written only by
  the worker that still holds the claim (ADR 0002).
- **Limits.** Workflow definitions up to 256 KB and 200 nodes; trigger payloads and step
  outputs up to `MAX_PAYLOAD_KB` (1 MiB); log lines truncated; execution deadline per
  workflow (`timeout_s`) and per node (`timeout_s`).
- **Event loops.** Events a workflow publishes carry a depth; past `EVENT_MAX_DEPTH` (5)
  they are recorded but start nothing. Executions started by an `execution.*` system event
  never publish `execution.*` events themselves, so a failure handler that fails cannot
  trigger itself, and test runs publish no system events.
- **Published versions are immutable** (a database trigger refuses updates) and every
  execution records the version it ran (ADR 0007).
- **Audit.** Every mutation (workflows, versions, activation, credentials, variables,
  members, API keys, cancels, resumes, retries, discarded dead letters, published events)
  writes an audit row with the actor; a trigger makes `audit_events` append-only.

## Infrastructure (AWS)

| Area | Control |
| --- | --- |
| Network | Tasks and RDS in private subnets; only the ALB is public; VPC flow logs; default security group denies all |
| TLS | ACM certificate on the ALB, HTTP redirects to HTTPS; RDS requires TLS (`rds.force_ssl`); Valkey uses TLS and an auth token |
| Encryption at rest | One customer-managed key for the bucket, queues, RDS, Valkey, Secrets Manager and logs; a separate vault key for credentials |
| Secrets | Session secret and API key pepper generated by Terraform into Secrets Manager; the RDS password is managed and rotated by RDS and read per connection (`DATABASE_SECRET_ARN`); `REDIS_URL` with its token in Secrets Manager; none appear in task definitions or plans |
| Containers | Non-root users, read-only root filesystem with a writable `/tmp`, tini as PID 1, no ECS exec |
| Edge | Optional WAF (AWS common, known bad inputs and IP reputation rule groups, per-IP rate limit) |
| Least privilege | One task role per service with exactly the calls that service makes; KMS use through the data key is limited by `kms:ViaService` |

## Operational guidance

- Rotate `SESSION_SECRET` to sign everyone out; rotate `API_KEY_PEPPER` to invalidate every
  API key. They are independent on purpose.
- Keep `OUTBOUND_ALLOW_PRIVATE_NETWORKS` off; list the few internal hosts workflows need.
- Give editors only to people who may act with the workflows' credentials: an editor can
  build a workflow that uses any credential of the workspace (without seeing it).
- Review the audit log for `credential.*`, `api_key.*` and `member.*` actions.
