#!/usr/bin/env bash
# Reproducible safety checks. Run from a clean clone with: make audit
# Needs uv and git. Node checks run if npm is available. Nothing here sends data anywhere except the
# package advisory lookup in pip-audit and npm audit.
set -u
cd "$(dirname "$0")/.."
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fails=0

check() {
  local name="$1"; shift
  if "$@" >"$TMP/out" 2>&1; then printf 'PASS  %s\n' "$name"
  else printf 'FAIL  %s\n' "$name"; tail -15 "$TMP/out"; fails=$((fails + 1)); fi
}

no_matches() {
  local pattern="$1"; shift
  ! git grep -nIE "$pattern" -- "$@"
}

sandboxed_demo() {
  # Blocks all non-loopback network at the OS level, then proves the block works before trusting the demo.
  local db="$TMP/demo.db"
  if command -v sandbox-exec >/dev/null; then
    local profile='(version 1)(allow default)(deny network-outbound (remote ip "*:*"))(allow network-outbound (remote ip "localhost:*"))'
    if sandbox-exec -p "$profile" curl -s --max-time 5 https://example.com >/dev/null 2>&1; then
      echo "network block did not work"; return 1
    fi
    DATABASE_URL="sqlite:///$db" sandbox-exec -p "$profile" .venv/bin/modellab demo
  elif unshare -rn true 2>/dev/null; then
    DATABASE_URL="sqlite:///$db" unshare -rn .venv/bin/modellab demo
  else
    echo "no OS network sandbox available here"; return 1
  fi
}

tracked_files_unchanged() { [ -z "$(git status --porcelain --untracked-files=no)" ]; }
locked_install() { uv sync -q --frozen; }
tests() { .venv/bin/python -m pytest -q; }
static_analysis() { uvx -q bandit -q -r apps/api packages services scripts --severity-level medium -x '*/migrations/*'; }
python_deps() {
  uv export -q --frozen --no-hashes --no-dev --all-extras --no-emit-project -o "$TMP/req.txt"
  uvx -q pip-audit -r "$TMP/req.txt" --no-deps --disable-pip
}
node_deps() { (cd apps/web && npm audit --audit-level=low); }
no_weights() { [ -z "$(git ls-files | grep -E '\.(safetensors|gguf|pt|bin|pkl)$')" ]; }
history_clean() { ! git log -p --all --format= | grep -E '^\+.*(ghp_[A-Za-z0-9]{20}|hf_[A-Za-z0-9]{20}|BEGIN [A-Z ]*PRIVATE KEY)'; }

check "Install matches the lockfile"                     locked_install
check "Test suite"                                       tests
check "Demo completes with outbound network blocked"     sandboxed_demo
check "Demo changes no tracked files"                    tracked_files_unchanged
check "Static analysis: no medium or high findings"      static_analysis
check "Python dependencies: no known vulnerabilities"    python_deps
if command -v npm >/dev/null; then check "Web dependencies: no known vulnerabilities" node_deps; fi
check "No model weights in Git"                          no_weights
check "No tokens or private keys in Git history"         history_clean
check "No dynamic code execution in source"              no_matches '\b(eval|exec)\(|pickle\.(load|loads)|shell=True|os\.system|yaml\.load\(|verify=False' 'apps/api/*.py' 'packages/*.py' 'services/*.py'
check "No committed .env"                                bash -c '[ -z "$(git ls-files | grep -E "(^|/)\.env$")" ]'

echo
if [ "$fails" -eq 0 ]; then echo "All checks passed."; else echo "$fails check(s) failed."; exit 1; fi
