# Run locally against real AWS

`make up` uses the Floci emulator. To check behaviour that an emulator cannot reproduce
(IAM policy evaluation, the vault key's encryption-context condition, SES sandbox rules,
real latency), run the same local containers against real AWS resources instead.

## How it works

`make up-aws` combines `deploy/compose/compose.yaml` with `compose.aws.yaml` instead of
`compose.floci.yaml`:

- Postgres, Valkey, the demo APIs, the API, the workers and the web app still run locally;
- there is no Floci, no Mailpit and no Terraform one-shot;
- the API, the workers and the migration job read `deploy/compose/.env.aws` and use your
  AWS profile (mounted read-only from `~/.aws`) for KMS, S3, SQS and SES.

## 1. Have the AWS resources

The simplest source is an `aws-dev` deployment ([deploy-aws.md](deploy-aws.md)); its
outputs name everything:

```bash
terraform -chdir=infra/terraform/envs/aws-dev output vault_key_alias
terraform -chdir=infra/terraform/envs/aws-dev output workflow_data_bucket
terraform -chdir=infra/terraform/envs/aws-dev output workflow_queue_urls
```

Your own resources work too: a symmetric KMS key, a bucket, queues and a verified SES
identity in one region.

Your AWS identity needs: `kms:GenerateDataKey`, `kms:Decrypt` and `kms:DescribeKey` on the
key; `s3:GetObject`, `s3:PutObject` and `s3:ListBucket` on the bucket; `sqs:SendMessage` and
`sqs:GetQueueUrl` on the queues; `ses:SendEmail` on the identity.

## 2. Write `.env.aws`

```bash
cp deploy/compose/.env.aws.example deploy/compose/.env.aws
```

```bash
AWS_REGION=us-east-1
KMS_KEY_ID=alias/wfe-dev-vault
WORKFLOW_DATA_BUCKET=wfe-dev-workflow-data
SQS_ALLOWED_QUEUES=wfe-dev-events
MAIL_FROM=Automations <automations@wfe.example.com>
```

Use a named profile by exporting `AWS_PROFILE` in your shell before `make up-aws`. The
file is ignored by git.

## 3. Start

```bash
make up-aws
make demo
```

The demo seed works the same way, with two differences: emails really go out through SES
(in the SES sandbox only to verified addresses, so expect the demo's email steps to fail
there), and the demo's `order-events` queue is not on your allowlist unless you add it, so
the order workflow's SQS step fails. Both failures show up as they would in production,
which is the point of this mode.

`make down` stops the containers; nothing in AWS is deleted.
