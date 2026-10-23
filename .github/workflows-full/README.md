# Full CI pipeline (opt-in)

These workflows are the complete quality pipeline for Euron WorkflowEngine. They are kept
here, outside `.github/workflows/`, so they do **not** run on the upstream repository. Only
the fast [`checks`](../workflows/checks.yml) workflow (lint, typecheck and unit tests for the
API and the web app, Terraform validation, the sanitization scan) runs there.

| Workflow | What it runs |
| --- | --- |
| [`ci.yml`](ci.yml) | API lint, typecheck and unit tests; web lint, typecheck, unit tests and build; the OpenAPI document matches the routes; the API integration suite against Postgres, Valkey, the Floci AWS emulator and Mailpit |
| [`security.yml`](security.yml) | gitleaks over the full history, CodeQL (Python and JavaScript/TypeScript), `pip-audit` and `pnpm audit` |
| [`terraform.yml`](terraform.yml) | `terraform fmt` and `validate` for every environment, tflint, checkov |
| [`docker.yml`](docker.yml) | Multi-arch image builds for `api` and `web`, pushed to GHCR on version tags |
| [`e2e.yml`](e2e.yml) | The full stack on the Floci emulator (`make up demo`), then the Playwright end-to-end tests and the QA crawl |

To enable them in your fork, move them into `.github/workflows/`:

```bash
git mv .github/workflows-full/*.yml .github/workflows/
```

Every gate is also runnable locally:
`make lint typecheck test test-integration e2e qa tf-validate tf-lint tf-security sanitize`.
