#!/usr/bin/env bash
# Write deploy/compose/.env with random, local-only secrets (once; never overwrites).
set -euo pipefail
f="$(cd "$(dirname "$0")/.." && pwd)/deploy/compose/.env"
if [[ -f "$f" ]]; then
  echo "deploy/compose/.env exists (delete it to regenerate)"
  exit 0
fi
rand() { openssl rand -base64 48 | tr -d '/+=\n' | cut -c1-"$1"; }
umask 077
cat >"$f" <<ENV
WFE_SESSION_SECRET=$(rand 64)
WFE_API_KEY_PEPPER=$(rand 64)
WFE_DEMO_PASSWORD=Demo-$(rand 12)
ENV
echo "wrote deploy/compose/.env"
