# Security Policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| 0.x (latest minor) | Yes |
| Older minors | No |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately through GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository ("Security" tab, "Report a vulnerability").

Please include:

- the affected component (`apps/api`, `apps/web`, `infra/terraform/...`) and version or commit,
- a description of the issue and its impact,
- steps to reproduce, or a proof of concept,
- any suggested mitigation.

What to expect:

| Stage | Target |
| ----- | ------ |
| Acknowledgement | within 3 business days |
| Initial assessment and severity | within 7 business days |
| Fix or mitigation for critical and high issues | within 30 days |
| Coordinated public disclosure | after a fix is released, credited to you unless you prefer otherwise |

## Scope

In scope: the code in this repository and the infrastructure it provisions with its
default settings. The most important classes of issue for this project are:

- reading or decrypting a stored credential through any API, log line or execution record,
- crossing a workspace boundary (reading or running another workspace's workflows,
  executions, credentials or events),
- executing arbitrary code through an expression, a template or a node configuration,
- reaching private network addresses from the HTTP or Slack nodes when the deployment has
  not allowed them,
- starting an execution through a signed webhook without the signing secret.

Out of scope:

- **What a workflow is configured to do.** An editor can build a workflow that sends any data
  a node can reach to any address the deployment allows. Restrict who holds the editor role.
- **The demo seed.** `make demo` creates well-known demo passwords on purpose and refuses to
  run with `APP_ENV=production`.
- Findings that require a compromised host, compromised AWS account, or leaked deployment
  secrets.
- Denial of service through resource exhaustion of a deployment you operate yourself.

## Hardening checklist for operators

See [docs/architecture/security.md](docs/architecture/security.md#operator-checklist).
