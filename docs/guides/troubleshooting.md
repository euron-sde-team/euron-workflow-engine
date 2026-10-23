# Troubleshooting

## Local stack

**`make up` says a port is already allocated.** Another program uses one of 3130, 8130,
5453, 6413, 4613, 9130 or 9131. Override the port in `deploy/compose/.env`, for example
`WFE_WEB_PORT=3230`, and run `make up` again. If you change `WFE_WEB_PORT` or
`WFE_API_PORT`, the compose file derives `CORS_ORIGINS`, `WEB_URL` and `API_URL` from them.

**`make up` waits for a long time on the first run.** It builds both images (the web app
build alone takes a few minutes) and Terraform applies 18 resources to the emulator.
`make logs SERVICE=terraform` shows the progress.

**The `terraform` service fails.** The emulator was not ready, or its volume holds state
from another version. `make down` (which deletes the volumes) and `make up` again.

**The `migrate` service fails.** `make logs SERVICE=migrate`. A database left over from an
older build with a different schema history: `make down` and start clean.

**`make demo` says the demo data is already present.** The seed runs once per database. To
start over: `make down && make up && make demo`.

**Docker runs out of memory.** The stack needs about 2 GB; give Docker at least 4 GB.

## Sign-in

**"Cross-site request blocked" (`csrf`).** The web app's origin is not in `CORS_ORIGINS` or
`WEB_URL`. Behind a proxy or on another port, set both to the address in the browser.

**Signed out after every request on a deployed instance.** `COOKIE_SECURE=true` requires
HTTPS end to end from the browser's point of view; on plain HTTP set it to `false` (never in
production).

**"Too many requests" on sign-in.** Ten attempts a minute per address. Wait a minute.

## Workflows and runs

**A webhook answers 404.** The workflow must be published and active, and the path in the
URL must match the trigger's path. Webhook URLs are shown in the editor on the trigger node.

**A webhook answers 401 `invalid_signature`.** The signature must be the HMAC-SHA256 of the
exact raw body with the webhook secret, hex encoded, with the configured prefix (`sha256=`)
in the configured header. Re-serialising the JSON before signing changes the bytes. With a
timestamp header, the signature covers `<timestamp>.<body>`.

**A schedule did not fire.** Only active workflows with a published version fire. The
dashboard shows the workers; if none is running, nothing fires. `next_fire_at` is on the
workflow list ("Next run"). A trigger with `overlap: skip` does not start while its previous
run is still active.

**A step fails with `blocked_address`.** The outbound guard refused a private, loopback,
link-local or metadata address. Add the host to `OUTBOUND_ALLOWED_HOSTS` if workflows really
must reach it.

**`bucket_not_allowed` or `queue_not_allowed`.** Add the bucket to `S3_ALLOWED_BUCKETS` or
the queue to `SQS_ALLOWED_QUEUES`.

**`read_only_violation` from the Postgres node.** The node runs read-only transactions
unless its mode is `read_write`.

**An execution stays `running` after a worker crashed.** The reaper requeues the step after
`STEP_STALE_S` (60 s). If no worker runs at all, start one.

**An execution is `queued` and does not start.** The workflow's concurrency limit is
reached; it starts when a running execution finishes.

**A step was retried although the error looks permanent, or the other way round.** Only
errors marked retryable are retried: timeouts, network errors and, for the HTTP request
node, the status codes in its `retry_on_status` setting. The step's error shows the
`retryable` flag; the retry policy is on the Settings tab of the node inspector.

## Email

**Nothing arrives locally.** Mail goes to Mailpit, not to real inboxes:
http://localhost:9130.

**`MessageRejected` on AWS.** `MAIL_FROM` must be on a verified SES identity in the same
region, and an account in the SES sandbox can only send to verified addresses.

## Credentials

**`vault_unavailable`.** KMS is not reachable or the task role may not use the vault key.
Locally, check that the `terraform` service completed. On AWS, the role may use the key only
with the credential's encryption context; a key from another deployment does not work.

**A credential cannot be deleted.** Workflows still reference it; the error lists them.

## Tests

**Integration tests cannot connect.** Start their services: `scripts/test-deps.sh up`
(ports 9135 to 9138), or run `make test-integration`, which does.

**Playwright tests fail with "Set DEMO_PASSWORD".** Run them through `make e2e` or
`make qa`, which read the password from `deploy/compose/.env`, after `make up && make demo`.

**The dead letter or cancel end-to-end tests fail on a reused stack.** They use the open
dead letters and waiting executions that `make demo` creates; after many runs there may be
none left. Reset with `make down && make up && make demo`.
