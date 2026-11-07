#!/usr/bin/env bash
# One command to a working dashboard: installs, seeds fixture data on first run, starts both services on loopback.
set -euo pipefail
cd "$(dirname "$0")/.."

need() { command -v "$1" >/dev/null || { echo "Missing $1. $2" >&2; exit 1; }; }
need uv "Install it from https://docs.astral.sh/uv/"
need npm "Install Node.js 20 or newer from https://nodejs.org/"

for port in 8100 3100; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port $port is already in use. Stop that process and try again." >&2
    exit 1
  fi
done

uv sync -q --frozen
[ -d apps/web/node_modules ] || (cd apps/web && npm ci --silent)
if [ ! -f .env ]; then
  (umask 077 && printf 'MODELLAB_ADMIN_TOKEN=%s\n' "$(openssl rand -hex 24)" > .env)
fi
set -a; . ./.env; set +a

[ -f var/modellab.db ] || uv run modellab demo
[ -f apps/web/.next/BUILD_ID ] || (cd apps/web && npm run build --silent)

pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
uv run modellab api >/dev/null & pids+=($!)
(cd apps/web && exec npm start --silent) >/dev/null & pids+=($!)

for _ in $(seq 1 60); do
  if curl -fs http://127.0.0.1:3100/api/health >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fs http://127.0.0.1:3100/api/health >/dev/null || { echo "The services did not start." >&2; exit 1; }
echo "ModelLab is running at http://127.0.0.1:3100 (press Ctrl+C to stop)"
wait
