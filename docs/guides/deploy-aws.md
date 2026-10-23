# Deploy to AWS

`infra/terraform` builds a complete deployment on ECS Fargate: a VPC, an Application Load
Balancer with TLS (and optionally WAF), RDS Postgres, ElastiCache Valkey, the workflow data
bucket, the workflow queues, an SES identity, two KMS keys, Secrets Manager secrets, ECR
repositories, CloudWatch alarms and a dashboard. `make aws-deploy` does everything in one
command.

```text
https://app.<domain>   web app                 (ECS service "web")
https://api.<domain>   API, docs, webhooks     (ECS service "api")
                       workers + scheduler      (ECS service "worker", no inbound traffic)
                       one-off CLI tasks        (task definition "cli")
```

Two environments are provided:

| | `aws-dev` | `aws-prod` |
| --- | --- | --- |
| Availability zones | 2, one NAT gateway | 3, a NAT gateway per zone |
| Database | single AZ, 3 days of backups | Multi-AZ, 14 days of backups |
| Valkey | no replica | one replica, automatic failover |
| WAF | off | on |
| Deletion protection | off | on (database, bucket, load balancer, registries) |
| Tasks (min to max) | api 1-2, worker 1-2, web 1-2 | api 2-6, worker 2-8, web 2-6 |
| Log retention | 14 days | 365 days |

## Prerequisites

- Terraform 1.10 or newer, Docker with `buildx`, the AWS CLI v2.
- Credentials for the target account with rights to create the resources above.
- A domain. The app is served at `app.<domain>` and the API at `api.<domain>`. With a
  Route53 hosted zone for it, certificates and DNS records are created for you.
- An SES identity to send from: a domain (recommended, verified through DKIM records that
  Terraform publishes in the zone) or a single address (verified by the link SES mails).
  New SES accounts start in the sandbox; request production access before workflows email
  customers.

## 1. Configure the environment

```bash
cd infra/terraform/envs/aws-dev
cp terraform.tfvars.example terraform.tfvars
```

| Variable | Required | Meaning |
| --- | --- | --- |
| `name_prefix` | yes | Prefix for every resource name, for example `wfe-dev` |
| `domain` | yes | Parent domain |
| `route53_zone_id` | recommended | Hosted zone of the domain |
| `certificate_arn` | without a zone | An ACM certificate covering `app.` and `api.` |
| `mail_identity` | yes | SES identity: `wfe.example.com` or `automations@example.com` |
| `mail_from` | yes | Sender on that identity, for example `Automations <automations@wfe.example.com>` |
| `workflow_queues` | no | Queues workflows may publish to, created as `<name_prefix>-<name>` (default `["events"]`) |
| `workflow_egress_ports` | no | Ports besides 443 workflow steps may reach (default `[80]`; add `5432` for external databases) |
| `outbound_allowed_hosts` | no | Internal host names workflows may call despite the private-network block |
| `alarm_email` | no | Receives the CloudWatch alarms (confirm the subscription email) |
| `db_instance_class`, `cache_node_type` | no | Sizes |

### Remote state

The state contains the generated secrets. For anything shared, keep it in S3:

```bash
cp backend.tf.example backend.tf   # then fill in a private, versioned, encrypted bucket
```

## 2. Deploy

```bash
make aws-deploy ENV=aws-dev
```

The script ([scripts/aws-deploy.sh](../../scripts/aws-deploy.sh)):

1. applies the ECR repositories (and the key that encrypts them);
2. builds the `api` and `web` images for `linux/arm64` and pushes them, tagged with the git
   commit;
3. applies everything else with that tag;
4. waits until the api, worker and web services are stable.

Migrations run when the first API task starts (`MIGRATE_ON_BOOT`, under an advisory lock).
To run them on their own: `make aws-migrate ENV=aws-dev`.

## 3. DNS

### With a Route53 zone

Nothing to do: the ACM certificate, its validation records, the `app.` and `api.` aliases
and the SES DKIM records are created in the zone.

### Without a Route53 zone

Publish what the outputs list, then run `make aws-deploy` again if the certificate was still
pending:

```bash
terraform -chdir=infra/terraform/envs/aws-dev output certificate_validation_records
terraform -chdir=infra/terraform/envs/aws-dev output load_balancer_dns_name   # CNAME app. and api. here
terraform -chdir=infra/terraform/envs/aws-dev output mail_dkim_tokens          # <token>._domainkey CNAMEs
```

## 4. Create the first account

```bash
make aws-cli ENV=aws-dev ARGS="user create --email you@example.com --name 'Your Name' --admin"
```

The command runs as a one-off Fargate task on the API image and prompts for nothing: pass
`--password` or set one at the first sign-in. Then open `https://app.<domain>`, sign in and
create the first workspace.

## What runs where

| Concern | Where |
| --- | --- |
| Session secret, API key pepper | Secrets Manager `<name_prefix>/app`, injected by ECS |
| Database password | Managed and rotated by RDS; tasks read it per connection (`DATABASE_SECRET_ARN`) |
| `REDIS_URL` with the auth token | Secrets Manager `<name_prefix>/cache` |
| Credentials vault | KMS key `alias/<name_prefix>-vault`, usable only with a credential's encryption context |
| Everything else at rest | KMS key `alias/<name_prefix>` |
| Logs | CloudWatch `/wfe/<name_prefix>/<service>` |
| Alarms | SNS topic `<name_prefix>-alarms`; dashboard `<name_prefix>` |

## Sizing

- **Workers** do the work. `WORKER_CONCURRENCY` (8 by default) steps run per task; most
  steps wait on the network, so CPU stays low and the autoscaler (CPU target 60%) adds tasks
  under heavy transformation load. Raise `worker_min_count` for steady throughput, keep it
  at 2 or more in production so the scheduler always has a standby.
- **API** load is the web app plus webhooks. Two tasks of 0.5 vCPU handle hundreds of
  webhooks a second.
- **Database** is the queue. `db.t4g.medium` is comfortable for thousands of steps a
  minute; watch `DatabaseConnections` (alarm at 80% of the ceiling) when adding tasks:
  each process opens up to `DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW` connections.

## Updating

Commit, then `make aws-deploy ENV=aws-dev` again. ECS rolls the services with a circuit
breaker that rolls back a deployment whose tasks do not become healthy. Workers finish
their running steps within `SHUTDOWN_GRACE_S`; anything still running when a task stops is
requeued by the reaper and retried.

## Tearing down

`aws-dev` has deletion protection off: `terraform -chdir=infra/terraform/envs/aws-dev destroy`.
For `aws-prod`, set `deletion_protection = false` in the module call, apply, then destroy.
KMS keys enter their deletion window; Secrets Manager secrets their recovery window.

## Next steps

- [Operations](operations.md): backups, rotation, scaling, alarms and logs.
- [Run the local stack against these resources](local-with-aws.md).
