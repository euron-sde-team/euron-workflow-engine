#!/usr/bin/env bash
# Start (or stop) the disposable services the integration suite needs, as a separate
# compose project on the extras ports: Postgres 9135, Valkey 9136, Floci 9137, Mailpit 9138.
#
#   scripts/test-deps.sh up      # start and wait until every service answers
#   scripts/test-deps.sh down    # stop and delete them (data lives in tmpfs anyway)
#   scripts/test-deps.sh env     # print the variables the suite reads
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose -f deploy/compose/compose.test-deps.yaml)
pg_port="${WFE_TEST_PG_PORT:-9135}"
redis_port="${WFE_TEST_REDIS_PORT:-9136}"
floci_port="${WFE_TEST_FLOCI_PORT:-9137}"
mailpit_port="${WFE_TEST_MAILPIT_PORT:-9138}"

print_env() {
  cat <<ENV
TEST_DATABASE_URL=postgresql+asyncpg://wfe:wfe@127.0.0.1:${pg_port}/wfe
TEST_REDIS_URL=redis://127.0.0.1:${redis_port}/0
TEST_AWS_ENDPOINT_URL=http://127.0.0.1:${floci_port}
TEST_MAILPIT_URL=http://127.0.0.1:${mailpit_port}
ENV
}

wait_http() { # url, attempts
  local url="$1" tries="${2:-60}"
  for _ in $(seq "$tries"); do
    if curl -s -o /dev/null "$url"; then return 0; fi
    sleep 1
  done
  echo "test-deps: $url did not answer" >&2
  return 1
}

case "${1:-up}" in
  up)
    log="$(mktemp)"
    trap 'rm -f "$log"' EXIT
    if ! "${compose[@]}" up -d --wait postgres redis mailpit floci >"$log" 2>&1; then
      cat "$log" >&2
      exit 1
    fi
    wait_http "http://127.0.0.1:${floci_port}/" 90
    wait_http "http://127.0.0.1:${mailpit_port}/api/v1/info" 30
    echo "test-deps: postgres :${pg_port}  valkey :${redis_port}  floci :${floci_port}  mailpit :${mailpit_port}"
    ;;
  down)
    "${compose[@]}" down -v --remove-orphans
    ;;
  env)
    print_env
    ;;
  *)
    echo "usage: scripts/test-deps.sh up|down|env" >&2
    exit 2
    ;;
esac
