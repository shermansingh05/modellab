#!/usr/bin/env bash
# End-to-end check against real processes: API, dashboard server, and a campaign driven through the proxy.
# Uses its own ports, token, and temporary database, so it can't touch your data.
set -euo pipefail
cd "$(dirname "$0")/.."
TMP="$(mktemp -d)"
API=18100; WEB=13100
export DATABASE_URL="sqlite:///$TMP/smoke.db" MODELLAB_ADMIN_TOKEN="smoke-$RANDOM$RANDOM" MODELLAB_API_URL="http://127.0.0.1:$API"
pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null || true; rm -rf "$TMP"; }
trap cleanup EXIT
fail() { echo "FAIL: $1" >&2; exit 1; }
status() { curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$@"; }

uv run --frozen modellab api --port "$API" >"$TMP/api.log" 2>&1 & pids+=($!)
(cd apps/web && exec npx next start -H 127.0.0.1 -p "$WEB") >"$TMP/web.log" 2>&1 & pids+=($!)
for _ in $(seq 1 60); do
  [ "$(status "http://127.0.0.1:$WEB/api/health")" = 200 ] && break
  sleep 1
done
[ "$(status "http://127.0.0.1:$WEB/api/health")" = 200 ] || { tail -5 "$TMP/api.log" "$TMP/web.log"; fail "services did not start"; }

for page in / /models /playground /experiments /campaigns /traces /benchmarks /training /reports; do
  [ "$(status "http://127.0.0.1:$WEB$page")" = 200 ] || fail "page $page"
done
echo "ok   all 9 dashboard pages respond"

ORIGIN="Origin: http://127.0.0.1:$WEB"
post() { curl -fsS --max-time 30 -X POST "http://127.0.0.1:$WEB/api$1" -H "$ORIGIN" -H 'content-type: application/json' -d "$2"; }
field() { uv run --frozen python -c "import json,sys;print(json.load(sys.stdin)['$1'])"; }

[ "$(status -X POST "http://127.0.0.1:$API/api/experiments" -H 'content-type: application/json' -d '{}')" = 401 ] || fail "API accepted a write with no token"
[ "$(status -X POST "http://127.0.0.1:$WEB/api/experiments" -H 'Origin: http://evil.example.test' -H 'content-type: application/json' -d '{}')" = 403 ] || fail "proxy accepted a foreign origin"
[ "$(status "http://127.0.0.1:$API/api/health" -H 'Host: evil.example.test')" = 400 ] || fail "API accepted a hostile Host"
echo "ok   writes need a token, foreign origins and hostile hosts are rejected"

BODY='{"name":"smoke","defenders":["mock-obedient"],"guardrails":["none","layered"],"scenarios":["pi-doc-exfil-slack","tm-delete-on-request","ctl-doc-summary"]}'
EXP="$(post /experiments "$BODY" | field id)"
RUN="$(post "/experiments/$EXP/run" '{}' | field id)"
for _ in $(seq 1 60); do
  STATE="$(curl -fs "http://127.0.0.1:$WEB/api/runs/$RUN" | field status)"
  [ "$STATE" = completed ] && break
  sleep 1
done
[ "$STATE" = completed ] || fail "run ended as $STATE"
echo "ok   campaign ran through the dashboard proxy"

curl -fs "http://127.0.0.1:$WEB/api/evaluations?run_id=$RUN" | uv run --frozen python -c "
import json, sys
m = {e['guardrail_preset']: e['metrics'] for e in json.load(sys.stdin)['items']}
assert m['none']['attack_success']['k'] == 2, m['none']['attack_success']
assert m['layered']['attack_success']['k'] == 0, m['layered']['attack_success']
assert m['layered']['benign_task_success']['k'] == 1, m['layered']['benign_task_success']
"
echo "ok   unguarded attacks succeeded, layered defense stopped them, the control task still passed"

curl -fs "http://127.0.0.1:$WEB/api/runs/$RUN/traces?guardrail=layered&scenario=tm-delete" | grep -q '"denied_by":"' || fail "no denied tool call in the trace"
curl -fs "http://127.0.0.1:$WEB/api/evaluations/$RUN/report?format=markdown" | grep -q "says nothing about any real model" || fail "report lacks the fixture warning"
echo "ok   trace shows the denied call, report carries provenance and the fixture warning"
echo "Smoke test passed."
