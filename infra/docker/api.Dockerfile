# syntax=docker/dockerfile:1.7
# -----------------------------------------------------------------------------
# API, workers, scheduler, migrations and the operator CLI: one image, three roles
# (docs/architecture/adr/0001-one-image-three-roles.md).
#   docker build -f infra/docker/api.Dockerfile -t wfe-api .
#
#   api        uvicorn workflow_engine.main:create_app --factory    (default command)
#   worker     wfe worker        claims steps; one replica also runs the scheduler
#   cli        wfe migrate | wfe user create | wfe demo seed | wfe demo-apis
# -----------------------------------------------------------------------------
ARG PYTHON_IMAGE=python:3.12.15-slim-bookworm
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.4

FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
# Dependencies first: this layer is reused until the lockfile changes.
COPY apps/api/pyproject.toml apps/api/uv.lock apps/api/README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY apps/api/src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM ${PYTHON_IMAGE} AS runtime
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=UTC
# Only these peers may set the client address through X-Forwarded-For (uvicorn reads this
# variable). The AWS deployment lists the VPC range, so the address the load balancer
# appends is used and anything a client prepends is ignored.
ENV FORWARDED_ALLOW_IPS=127.0.0.1
# tini forwards SIGTERM, so uvicorn drains requests and workers finish their steps.
RUN apt-get update && apt-get install -y --no-install-recommends tini ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 10001 --user-group --no-create-home --home-dir /app wfe
WORKDIR /app
COPY --from=build --chown=wfe:wfe /app/.venv /app/.venv
USER wfe
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/livez', timeout=2).status == 200 else 1)"]
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "workflow_engine.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", \
     "--proxy-headers", "--timeout-graceful-shutdown", "20", "--no-access-log"]
