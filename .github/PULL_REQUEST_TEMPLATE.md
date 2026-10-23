## What and why

<!-- One paragraph: the problem, and how this change solves it. Link the issue. -->

## How it was verified

- [ ] `make lint typecheck test`
- [ ] `make test-integration` (if API, database, engine, worker, scheduler or AWS code changed)
- [ ] `make e2e` (if a user flow, the web app or the infrastructure changed)
- [ ] `make tf-validate tf-lint tf-security` (if Terraform changed)

## Checklist

- [ ] Docs updated (`docs/`, the configuration reference) for any behavior or config change
- [ ] `make openapi` re-run if a route changed
- [ ] New migration instead of editing an applied one
- [ ] Workspace data stays in its workspace: covered by a test
- [ ] A new node type ships with a config model, a unit test and a catalog entry
- [ ] No secrets, account ids, real emails or hostnames (`make sanitize` is clean)
- [ ] Security-relevant change? Described the threat and mitigation above
