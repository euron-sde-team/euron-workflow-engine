# Testing

| Suite | Count | Runs against | Command |
| --- | --- | --- | --- |
| API unit tests | 208 | Nothing: pure functions, fakes for Redis and AWS | `make test` |
| Web unit tests (Vitest) | 38 | Nothing | `make test` |
| API integration tests | 56 | Real Postgres, Valkey, the Floci AWS emulator and Mailpit, the real worker and scheduler | `make test-integration` |
| Browser end-to-end tests (Playwright) | 13 | The full local stack with demo data | `make e2e` |
| QA crawl (Playwright and axe) | 4 (every page, desktop and mobile) | The full local stack with demo data | `make qa` |
| Screenshots and tour | 3 | The full local stack with demo data | `make screenshots` |

## Unit tests

```bash
make test                      # pytest tests/unit, then Vitest
cd apps/api && uv run pytest tests/unit -q -k routing
```

What they cover, by module:

- **engine**: cron parsing and DST rules, JMESPath functions, templates, graph validation,
  routing (branches, OR joins, merges, loops with scopes, dead-path elimination) driven
  through a simulator, backoff with jitter, conditions;
- **nodes**: every node type with fake services (HTTP through `respx`, S3, SQS, SES, KMS
  fakes), configuration validation, the outbound network guard (private ranges, DNS answers
  that change, redirects);
- **core**: configuration and the production refusals, passwords, sessions and API keys,
  crypto, rate limits, the database password from Secrets Manager;
- **web** (`apps/web/src/**/*.test.ts`): the API client, formatting, graph conversion, JSON
  schema defaults, credential forms, execution grouping and the timeline layout, time zones.

## Integration tests

```bash
make test-integration          # starts the services, then pytest tests/integration
scripts/test-deps.sh down      # stop them
```

`scripts/test-deps.sh` runs Postgres (`9135`), Valkey (`9136`), Floci (`9137`) and Mailpit
(`9138`) as their own compose project, so the suite never touches the `make up` stack. The
suite creates its own database, migrates it, provisions a KMS key, a bucket, queues and an
SES identity in the emulator, starts the demo APIs, and runs the real API in process with a
real worker and scheduler.

What they prove, among others:

- a linear run, branches and merges, loops that call an API per batch;
- idempotency keys returning the same execution;
- retries with backoff, dead letters and resume from the failed step, `on_error: continue`,
  node and execution timeouts, waits and wake-ups, cancellation of waiting and running
  executions, per-workflow concurrency limits, payload limits;
- 12 racing claimers never claim a step twice; a reaped worker cannot write its result;
- signed webhooks (HMAC, timestamps against replay, bearer), synchronous webhook answers,
  events with filters and wildcards, event chains and failure handlers that cannot loop;
- a schedule fires exactly once per tick with two schedulers;
- KMS envelope encryption, and a credential moved to another workspace cannot be opened;
- every workspace route answers 404 to a non-member, and nothing changes;
- SES mail arriving in Mailpit, S3 round trips, the SQS allowlist, read-only Postgres;
- the dashboard aggregates and the whole demo seed.

## Browser end-to-end tests

```bash
make up && make demo
make e2e                       # Playwright, Chromium, against http://localhost:3130
```

| File | Journeys |
| --- | --- |
| `e2e/tests/auth.spec.ts` | Wrong password, sign in and out, return to the page after signing in |
| `e2e/tests/editor.spec.ts` | Build a workflow on the canvas, test a node, run the draft, publish and activate; use a template; a viewer cannot change anything |
| `e2e/tests/executions.spec.ts` | A signed webhook runs the order workflow with a retry, idempotency; cancel a waiting execution; filter failed runs; retry a dead letter |
| `e2e/tests/operate.spec.ts` | Publish an event that starts a workflow; write-only credentials; variables, API keys and the audit log |

The suites share the demo database and change it (they cancel a waiting execution and
retry a dead letter). On a long-lived stack, reset with `make down && make up && make demo`.

## QA crawl

```bash
make qa
```

Visits every page signed in as the owner, at 1440x900 and 390x844, and fails on console
errors, uncaught exceptions, failed or 4xx/5xx requests, sideways scrolling, broken
internal links and serious or critical axe violations (WCAG 2.1 A and AA). A full-page
capture of every page lands in `e2e/.qa/` for a visual review.

## Screenshots

```bash
make screenshots
```

Captures the README screenshots at 1440x900 and 2x into `docs/assets/screenshots/` and
assembles `docs/assets/tour.gif` from the tour frames, from a freshly seeded stack.

## Infrastructure checks

```bash
make tf-fmt tf-validate        # every environment, no credentials needed
make tf-lint                   # tflint with the AWS ruleset
make tf-security               # checkov: any finding without an inline justification fails
make sanitize                  # credentials, account ids and resource ids in committable files
```

## Continuous integration

`.github/workflows/checks.yml` runs on every push: API and web lint, typecheck and unit
tests, Prettier, Terraform fmt and validate, and the sanitization scan. The full pipeline
(integration tests, the OpenAPI check, image builds, the end-to-end suite on Floci,
gitleaks, CodeQL, dependency audits, tflint and checkov) is in `.github/workflows-full/`,
ready to enable in a fork.
