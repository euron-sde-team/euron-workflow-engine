# ADR 0008: Develop against the Floci AWS emulator, provisioned by the production Terraform

## Status

Accepted.

## Context

In production WorkflowEngine depends on four AWS services, and three of them sit on
security-critical paths:

- **KMS** wraps the data key of every stored credential (ADR 0006), with an encryption
  context that binds it to its workspace and credential id;
- **S3** is the target of the S3 get and put nodes (the workflow data bucket, SSE-KMS);
- **SQS** is the target of the SQS publish node (allowlisted queues with dead-letter
  queues);
- **SES** sends the mail of the email node.

Local development that swaps each of them for something else (a static key, a folder, a
log line, an SMTP catcher) leaves exactly those code paths untested until they meet a real
account. The Terraform that builds them also needs a place to run on every change without
credentials.

## Decision

- `make up` runs the Floci emulator (`floci/floci:2.3.0`, MIT licence) next to Postgres,
  Valkey, Mailpit and the application images.
- A one-shot Terraform container applies `infra/terraform/envs/local-floci` against the
  emulator before the migrations, the API and the workers start. That environment uses
  the **same** `kms`, `storage`, `queues`, `email` and `secrets` modules as `aws-dev` and
  `aws-prod`; only the endpoints and a few emulator switches differ (no TLS-only bucket
  policy, versioning off, force-destroy on, no SES configuration set).
- The application runs with `VAULT_PROVIDER=kms` and `AWS_ENDPOINT_URL` pointing at the
  emulator, so credentials are sealed with real `GenerateDataKey` and `Decrypt` calls and
  encryption contexts.
- Floci relays every SES message to Mailpit, so mail sent by workflows is readable in a
  browser at `localhost:9130`.
- The integration suite runs against its own disposable Floci (`scripts/test-deps.sh`,
  ports 9135 to 9138), creating keys, buckets, queues and identities per run.
- Terraform state for the local environment lives in a Docker volume and is wiped with the
  emulator by `make down`.

## Consequences

Positive:

- Developers and CI exercise the real SDK calls, KMS encryption contexts, SSE-KMS
  buckets, queue allowlists and SES sends without an AWS account or a paid key.
- The infrastructure modules are applied on every `make up`, not only on deploy.
- Mail and Slack messages produced by the demo are observable end to end.

Trade-offs:

- An emulator is not AWS. IAM policy evaluation (including the vault key's
  encryption-context condition), service quotas, the SES sandbox and real DNS are not
  reproduced; [deploy-aws.md](../../guides/deploy-aws.md) and `make up-aws` cover the gap.
- One more container and image version to keep current.

## Alternatives considered

- **Per-service local substitutes** (a static key, MinIO, an SMTP catcher). Simple, but
  the KMS and SES code paths would go untested locally.
- **LocalStack.** A comparable emulator offering the same approach; Floci is the one this
  project is built and tested against, and the other Euron projects use it too.
- **A shared development AWS account.** Highest fidelity, but needs credentials for every
  contributor, costs money, and shared state makes tests interfere with each other.
