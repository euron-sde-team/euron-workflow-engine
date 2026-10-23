# Euron WorkflowEngine: developer entry points. `make` lists every target.
SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

COMPOSE_DIR := deploy/compose
FLOCI       := docker compose --env-file $(COMPOSE_DIR)/.env -f $(COMPOSE_DIR)/compose.yaml -f $(COMPOSE_DIR)/compose.floci.yaml
AWS_LOCAL   := docker compose --env-file $(COMPOSE_DIR)/.env -f $(COMPOSE_DIR)/compose.yaml -f $(COMPOSE_DIR)/compose.aws.yaml
API         := uv --directory apps/api run
TF_IMAGE    := hashicorp/terraform:1.16.6
TF_ENVS     := local-floci aws-dev aws-prod
# Use a local terraform when installed, otherwise the pinned container.
TF          := $(shell command -v terraform >/dev/null 2>&1 && echo terraform || echo docker run --rm -v $(CURDIR)/infra/terraform:/infra -v wfe-tf-plugins:/plugins -e TF_PLUGIN_CACHE_DIR=/plugins -e TF_DATA_DIR=/tmp/tfdata -w /infra $(TF_IMAGE))
TF_ROOT     := $(shell command -v terraform >/dev/null 2>&1 && echo infra/terraform || echo /infra)
# The browser suites sign in as the demo accounts seeded by `make demo`.
DEMO_PASSWORD = $(shell grep -s '^WFE_DEMO_PASSWORD=' $(COMPOSE_DIR)/.env | cut -d= -f2)
ENV         ?= aws-dev
TAG         ?= $(shell git rev-parse --short=12 HEAD 2>/dev/null || echo dev)

.PHONY: help env up up-aws down logs ps demo test test-integration test-deps-down e2e qa \
        screenshots lint format typecheck build openapi sanitize tf-fmt tf-validate tf-lint \
        tf-security aws-plan aws-deploy aws-migrate aws-cli clean

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make \033[36m<target>\033[0m\n\n"} /^[a-zA-Z0-9_-]+:.*##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# --- Local -------------------------------------------------------------------

env: ## Generate deploy/compose/.env with random local-only secrets
	@scripts/gen-local-env.sh

up: env ## Start everything on emulated AWS (Floci), provisioned by the same Terraform as production
	$(FLOCI) up -d --build --wait
	@echo ""
	@echo "  web        http://localhost:$${WFE_WEB_PORT:-3130}"
	@echo "  api        http://localhost:$${WFE_API_PORT:-8130}/docs"
	@echo "  mail       http://localhost:$${WFE_MAILPIT_PORT:-9130}   (everything the email node sends)"
	@echo "  demo APIs  http://localhost:$${WFE_DEMO_APIS_PORT:-9131}/slack   (Slack messages)"
	@echo ""
	@echo "  Next: make demo   (accounts, templates as live workflows, two weeks of real runs)"

up-aws: env ## Start the stack against real AWS resources (needs deploy/compose/.env.aws)
	@test -f $(COMPOSE_DIR)/.env.aws || { echo "copy $(COMPOSE_DIR)/.env.aws.example to .env.aws first"; exit 1; }
	$(AWS_LOCAL) up -d --build --wait

demo: ## Seed the Northwind workspace with workflows and real execution history (prints the logins)
	$(FLOCI) exec -T -e DEMO_PASSWORD=$(DEMO_PASSWORD) api wfe demo seed

down: ## Stop the stack and delete its volumes
	-$(FLOCI) down -v --remove-orphans
	-$(AWS_LOCAL) down -v --remove-orphans 2>/dev/null

logs: ## Tail logs (SERVICE=api|worker|web|migrate|demo-apis|postgres|valkey|floci|terraform|mailpit)
	$(FLOCI) logs -f --tail 100 $(SERVICE)

ps: ## Show stack status
	$(FLOCI) ps

# --- Quality -----------------------------------------------------------------

lint: ## Lint and check formatting (ruff, ESLint, Prettier)
	$(API) ruff check . && $(API) ruff format --check .
	pnpm lint
	pnpm format:check

format: ## Format every file (ruff, Prettier)
	$(API) ruff check --fix . && $(API) ruff format .
	pnpm format

typecheck: ## Typecheck (mypy strict, tsc)
	$(API) mypy
	pnpm typecheck

test: ## Unit tests (pytest, Vitest)
	$(API) pytest tests/unit -q
	pnpm test

test-integration: ## API integration tests against real Postgres, Valkey, Floci and Mailpit (started if needed)
	@scripts/test-deps.sh up
	$(API) pytest tests/integration -q

test-deps-down: ## Stop the integration test services
	@scripts/test-deps.sh down

e2e: ## Browser end-to-end tests (Playwright) against the running stack (make up demo first)
	DEMO_PASSWORD=$(DEMO_PASSWORD) pnpm e2e

qa: ## Crawl every page at desktop and mobile widths; fails on console errors and axe violations
	DEMO_PASSWORD=$(DEMO_PASSWORD) pnpm qa

screenshots: ## README screenshots (1440x900 @2x) and docs/assets/tour.gif from the running stack
	DEMO_PASSWORD=$(DEMO_PASSWORD) pnpm capture

build: ## Build the web app and both images
	pnpm build
	docker build -f infra/docker/api.Dockerfile -t wfe-api:local .
	docker build -f infra/docker/web.Dockerfile -t wfe-web:local .

openapi: ## Regenerate docs/api/openapi.json from the routes
	$(API) wfe openapi --out ../../docs/api/openapi.json

sanitize: ## Scan committable files for credentials and cloud identifiers
	@scripts/check-sanitization.sh

# --- Terraform ---------------------------------------------------------------

tf-fmt: ## Format all Terraform
	$(TF) fmt -recursive $(TF_ROOT)

tf-validate: ## terraform validate every environment (no backend, no credentials)
	@for env in $(TF_ENVS); do \
	  echo "== $$env"; \
	  $(TF) -chdir=$(TF_ROOT)/envs/$$env init -backend=false -input=false -no-color >/dev/null && \
	  $(TF) -chdir=$(TF_ROOT)/envs/$$env validate -no-color || exit 1; \
	done

tf-lint: ## tflint every module and environment (plugins cached in a docker volume)
	docker run --rm -v $(CURDIR)/infra/terraform:/data -v wfe-tflint:/plugins -e TFLINT_PLUGIN_DIR=/plugins -w /data ghcr.io/terraform-linters/tflint:v0.64.0 --init
	docker run --rm -v $(CURDIR)/infra/terraform:/data -v wfe-tflint:/plugins -e TFLINT_PLUGIN_DIR=/plugins -w /data ghcr.io/terraform-linters/tflint:v0.64.0 --recursive --format compact

tf-security: ## checkov policy scan of the Terraform (any unskipped finding fails)
	docker run --rm -v $(CURDIR)/infra/terraform:/tf bridgecrew/checkov:3.3.30 -d /tf --framework terraform --quiet --compact --config-file /tf/.checkov.yaml

# --- AWS ---------------------------------------------------------------------

aws-plan: ## terraform plan for ENV (aws-dev | aws-prod); needs terraform.tfvars and AWS credentials
	cd infra/terraform/envs/$(ENV) && terraform init -input=false && terraform plan -var image_tag=$(TAG)

aws-deploy: ## One shot: registries, images, infrastructure, rollout (ENV=aws-dev|aws-prod)
	@scripts/aws-deploy.sh $(ENV) $(TAG)

aws-migrate: ## Run database migrations as a one-off ECS task (ENV=...)
	@scripts/aws-run-task.sh $(ENV) wfe migrate

aws-cli: ## Any wfe CLI command as a one-off ECS task (ENV=... ARGS="user create --email ...")
	@test -n "$(ARGS)" || { echo 'usage: make aws-cli ARGS="user create --email you@example.com --name You --admin"'; exit 1; }
	@scripts/aws-run-task.sh $(ENV) wfe $(ARGS)

clean: ## Remove build output and caches
	rm -rf apps/web/.next e2e/test-results e2e/playwright-report e2e/.qa e2e/.auth apps/api/.pytest_cache apps/api/.mypy_cache apps/api/.ruff_cache
