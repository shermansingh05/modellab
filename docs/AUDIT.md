# Security audit

**This is a self-assessment by the project's author, done with AI assistance. It is not an independent penetration test or a certification.** Everything below can be reproduced, so please check it yourself.

```bash
git clone https://github.com/shermansingh05/modellab.git && cd modellab
uv sync --frozen && (cd apps/web && npm ci)
make audit
```

## Is it safe to run?

**The deterministic demo is low risk.** It needs no GPU, model download, or services, and it completed with all outbound network blocked by the operating system. It writes only to an ignored `var/` folder inside the repository, plus a temporary database under `make audit`.

**Real-model runs need more thought.** They require installing Ollama and downloading third-party weights, and one of those models has had its safety behavior removed. Get approval before doing that on a corporate device. The sandbox is logical rather than enforced by the OS, so use a dedicated research machine if your policy requires isolation.

| You run | Network | Writes to | Risk notes |
|---|---|---|---|
| `make audit` | Package advisory lookups, plus package downloads on a first install | `.venv`, a temp folder | None beyond installing dependencies |
| `modellab demo` | None | `var/` | Uses fixtures only |
| API and dashboard | Loopback only | `var/` | Admin token lives in `.env`, which is ignored by Git |
| `modellab eval run` with real models | Loopback to Ollama | `var/` | Runs model-generated tool calls against in-memory fixtures only |
| `modellab models pull` | Ollama or Hugging Face | Backend's model store | Third-party weights, 5 GB or more |

## Results

| Check | Result |
|---|---|
| Test suite from a clean clone | 141 passed, 2 skipped (the 2 need live Ollama and Postgres, and passed when run separately) |
| End-to-end smoke test (`make smoke`) | Real API and dashboard processes run a campaign through the proxy, and CI repeats it on every push |
| Demo with outbound network denied by macOS `sandbox-exec` | Passed, after confirming the block stops `curl` |
| Tracked files changed by the demo | None |
| Static analysis (Bandit, medium and above) | No findings |
| Python dependencies, including optional extras (`pip-audit`) | No known vulnerabilities on the audit date |
| Web dependencies (`npm audit`) | No known vulnerabilities on the audit date |
| Secrets in Git history (pattern scan and `detect-secrets`) | None. Flagged items were commit hashes, a fake test key, and a CI-only database password |
| Model weights in Git | None |
| Dynamic code execution in source (`eval`, `exec`, pickle loading, shell commands) | None |

### Live attacks on the running API

| Attempt | Response |
|---|---|
| Start an experiment with no token | 401 |
| Run inference with no token, or the wrong token | 401 |
| Cancel a run with no token | 401 |
| Invalid request with a valid token | 422 |
| Hostile Host header, simulating DNS rebinding | 400 |
| Dashboard proxy: POST from another site's Origin | 403 |
| Dashboard proxy: hostile Host | 403 |
| Dashboard proxy: encoded path traversal | 404 |
| Admin token present in the browser bundle | Not found |

The API, dashboard, and Ollama were all listening on `127.0.0.1` only.

## Vulnerabilities found and fixed

| Severity | Finding | Fix |
|---|---|---|
| **High** | Model-written SQL could create files on the host through `ATTACH DATABASE` and `VACUUM INTO`. No model attempted this in recorded runs. | A SQLite authorizer denies these operations, with regression tests |
| Medium | An endless recursive SQL query could hang a run | Query time limit and row cap |
| Medium | A hostile website could reach the loopback API through DNS rebinding | Host header allowlist |
| Medium | 15 known advisories in the main dependencies, plus some in optional ML packages | Upgraded |
| Low | Malformed tool arguments could crash a run instead of failing one call | Handled, with a test |
| Low | Tool arguments on disallowed requests could store harmful text | Withheld |
| Low | Personal email in commit metadata | History rewritten to a no-reply address before publishing |

Four measurement bugs were also found by auditing real trials. For the first two, all results produced before the fixes were discarded and rerun. The third counted calls to nonexistent tools as unauthorized executions, and it was corrected from stored evidence with `modellab eval regrade`, which is recorded in the affected reports. The fourth only counted denied tool calls as false positives, which hid a classifier blocking 15 of 24 legitimate control tasks, so the metric now counts any intervention on a control task.

Dependency updates aren't merged on CI alone. A Monaco editor update passed CI but pulled in a critical `dompurify` advisory and broke its web workers, so it was reverted.

## Residual risks

- **The sandbox is logical.** Tools only touch in-memory state by design, but no container or seccomp profile enforces that.
- **Read routes have no authentication.** They rely on loopback binding and the Host check, so any local process can read traces.
- **Weights are trusted once pulled.** Ollama pulls are recorded by digest, not independently verified.
- **The scans have limits.** Pattern-based secret scanning and static analysis can miss things, and advisory results change over time. Re-run `make audit`.
- **The Linux network-block path in `make audit` hasn't been tested.** It was only run on macOS.
- **Written but not exercised:** the Transformers and vLLM adapters, the Dramatiq worker, and Docker Compose. See [limitations](limitations.md).

See the [threat model](threat-model.md) for the full picture.
